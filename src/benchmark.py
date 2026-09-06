"""
File: benchmark.py
Author: citrus
Abstract:
S3互換オブジェクトストレージ（MinIO・SeaweedFS・Garage）ベンチマーク
"""

from __future__ import annotations

import argparse
import io
import json
import sys
import time
from pathlib import Path

import boto3
import botocore.config
import botocore.exceptions
import polars as pl
from mypy_boto3_s3 import S3Client

import garage
import minio
import seaweedfs
from generate_data import generate_parquet_file
from models import FeatureResult, OperationResult, StorageConfig, WorkloadConfig

# ── S3クライアント・バケット管理 ────────────────────────────────────────────


def create_client(config: StorageConfig) -> S3Client:
    """StorageConfig からS3クライアントを生成する．

    フレキシブルチェックサム（CRC32等）の計算・検証を無効化する．
    S3互換ストレージはマルチパートアップロード時の合成チェックサム仕様が
    AWS S3と異なり，boto3側の検証が不一致で失敗するため（Garageのlargeで顕在化）．
    全バックエンドで同一設定とし，比較の公平性を保つ．

    Args:
        config: 接続先ストレージの設定．

    Returns:
        boto3 S3クライアント．
    """
    return boto3.client(
        "s3",
        endpoint_url=config.endpoint_url,
        aws_access_key_id=config.access_key,
        aws_secret_access_key=config.secret_key,
        region_name=config.region,
        config=botocore.config.Config(
            request_checksum_calculation="when_required",
            response_checksum_validation="when_required",
        ),
    )


def setup_bucket(client: S3Client, bucket: str) -> None:
    """バケットが存在しない場合に作成する．

    Args:
        client: S3クライアント．
        bucket: バケット名．

    Raises:
        botocore.exceptions.ClientError: 404以外のエラーが発生した場合．
    """
    try:
        client.head_bucket(Bucket=bucket)
    except botocore.exceptions.ClientError as e:
        if e.response["Error"]["Code"] in ("404", "NoSuchBucket"):
            client.create_bucket(Bucket=bucket)
        else:
            raise


def teardown_bucket(client: S3Client, bucket: str) -> None:
    """バケット内の全オブジェクトを削除し，バケットの削除を試みる．

    オブジェクト削除（次バックエンドのための容量解放）を主目的とし，
    空バケットの削除は後片付けとして扱う．Garageは事前作成したバケットを
    S3 DeleteBucket で削除できない（グローバルエイリアス仕様）ため，
    delete_bucket の失敗は警告のみで無視する．finally から呼ばれても
    計測フェーズの例外を隠さないようにする狙いもある．

    Args:
        client: S3クライアント．
        bucket: バケット名．
    """
    paginator = client.get_paginator("list_objects_v2")
    for page in paginator.paginate(Bucket=bucket):
        objects = [{"Key": obj["Key"]} for obj in page.get("Contents", [])]
        if objects:
            client.delete_objects(Bucket=bucket, Delete={"Objects": objects})
    try:
        client.delete_bucket(Bucket=bucket)
    except botocore.exceptions.ClientError as e:
        print(f"警告: バケット '{bucket}' の削除をスキップしました: {e}", file=sys.stderr)


# ── 単一オペレーション計測 ──────────────────────────────────────────────────


def measure_put(
    client: S3Client,
    bucket: str,
    key: str,
    data: bytes,
    storage: str,
    workload: str,
    trial: int,
) -> OperationResult:
    """PUTオペレーションのレイテンシとスループットを計測する．

    Args:
        client: S3クライアント．
        bucket: バケット名．
        key: オブジェクトキー．
        data: アップロードするデータ．
        storage: バックエンド識別子．
        workload: ワークロード識別子．
        trial: 試行番号．

    Returns:
        計測結果．
    """
    size_bytes = len(data)
    start = time.perf_counter()
    client.upload_fileobj(io.BytesIO(data), bucket, key)
    elapsed_ms = (time.perf_counter() - start) * 1000
    throughput_mbps = (size_bytes / 1024 / 1024) / (elapsed_ms / 1000)
    return OperationResult(
        storage, "PUT", workload, trial, key, size_bytes, elapsed_ms, throughput_mbps
    )


def measure_get(
    client: S3Client,
    bucket: str,
    key: str,
    size_bytes: int,
    storage: str,
    workload: str,
    trial: int,
) -> OperationResult:
    """GETオペレーションのレイテンシとスループットを計測する．

    Args:
        client: S3クライアント．
        bucket: バケット名．
        key: オブジェクトキー．
        size_bytes: オブジェクトサイズ (bytes)．スループット算出に使用．
        storage: バックエンド識別子．
        workload: ワークロード識別子．
        trial: 試行番号．

    Returns:
        計測結果．
    """
    start = time.perf_counter()
    resp = client.get_object(Bucket=bucket, Key=key)
    resp["Body"].read()
    elapsed_ms = (time.perf_counter() - start) * 1000
    throughput_mbps = (size_bytes / 1024 / 1024) / (elapsed_ms / 1000)
    return OperationResult(
        storage, "GET", workload, trial, key, size_bytes, elapsed_ms, throughput_mbps
    )


def measure_delete(
    client: S3Client,
    bucket: str,
    key: str,
    size_bytes: int,
    storage: str,
    workload: str,
    trial: int,
) -> OperationResult:
    """DELETEオペレーションのレイテンシを計測する．

    DELETEはボディ転送を伴わないため，スループット (MB/s) という指標自体が
    意味を持たない（`size_bytes / elapsed` を計算すると数万MB/s等の無意味な値になる）．
    そのためDELETEはレイテンシのみを指標とし，`throughput_mbps` は None を返す．
    `size_bytes` はCSV記録用（他オペレーションとの列統一・集計時の参照用）に残す．

    Args:
        client: S3クライアント．
        bucket: バケット名．
        key: オブジェクトキー．
        size_bytes: オブジェクトサイズ (bytes)．CSV記録用．スループット算出には使用しない．
        storage: バックエンド識別子．
        workload: ワークロード識別子．
        trial: 試行番号．

    Returns:
        計測結果．`throughput_mbps` は常に None．
    """
    start = time.perf_counter()
    client.delete_object(Bucket=bucket, Key=key)
    elapsed_ms = (time.perf_counter() - start) * 1000
    return OperationResult(
        storage, "DELETE", workload, trial, key, size_bytes, elapsed_ms, None
    )


def run_operation_measurement(
    client: S3Client,
    bucket: str,
    workload: WorkloadConfig,
    storage: str,
    data_dir: Path,
) -> list[OperationResult]:
    """PUT・GET・DELETEを全ファイルに対して n_trial 回繰り返し計測する．

    計測前に全ファイルをメモリへ読み込み，ローカルI/Oを計測から除外する．

    Args:
        client: S3クライアント．
        bucket: バケット名．
        workload: ワークロードパラメータ．
        storage: バックエンド識別子．
        data_dir: Parquetファイルが格納されたディレクトリ．

    Returns:
        PUT・GET・DELETE各オペレーションの計測結果リスト．
    """
    # 計測ループ前にすべてメモリへ読み込み，ローカルI/Oを除外する
    files = sorted(data_dir.glob("*.parquet"))[: workload.n_file]
    file_data: list[tuple[int, bytes]] = [
        (i, p.read_bytes()) for i, p in enumerate(files)
    ]

    results: list[OperationResult] = []
    for trial in range(workload.n_trial):
        for i, data in file_data:
            key = f"{workload.name}/{trial}/{i}.parquet"
            results.append(
                measure_put(client, bucket, key, data, storage, workload.name, trial)
            )

        for i, data in file_data:
            key = f"{workload.name}/{trial}/{i}.parquet"
            results.append(
                measure_get(
                    client, bucket, key, len(data), storage, workload.name, trial
                )
            )

        for i, data in file_data:
            key = f"{workload.name}/{trial}/{i}.parquet"
            results.append(
                measure_delete(
                    client, bucket, key, len(data), storage, workload.name, trial
                )
            )

    return results


# ── 機能検証 ────────────────────────────────────────────────────────────────

_PROBE_KEY = "feature-probe.parquet"
_PROBE_SIZE = 1024 * 1024  # 1 MB


def validate_head(
    client: S3Client,
    bucket: str,
    key: str,
    expected_size: int,
    storage: str,
) -> FeatureResult:
    """HEADオペレーションの動作を検証する．

    仕様（docs/benchmark_spec.md）上の成功条件は「ClientErrorが発生せず，
    ContentLengthがPUT時のサイズと一致する」のみ．ContentTypeの有無は
    バックエンドによって省略されうる参考情報のため，判定条件には含めない
    （以前はContentTypeの存在を条件に含めていたため，Garageのように
    ContentTypeを返さない実装で例外なく false と誤記録されていた）．

    Args:
        client: S3クライアント．
        bucket: バケット名．
        key: 検証対象オブジェクトキー．
        expected_size: 期待するオブジェクトサイズ (bytes)．
        storage: バックエンド識別子．

    Returns:
        機能検証結果．
    """
    try:
        resp = client.head_object(Bucket=bucket, Key=key)
        ok = resp.get("ContentLength") == expected_size
        return FeatureResult(storage, "HEAD", ok, None)
    except Exception as e:
        return FeatureResult(storage, "HEAD", False, str(e))


def validate_tagging(
    client: S3Client,
    bucket: str,
    key: str,
    storage: str,
) -> FeatureResult:
    """オブジェクトタグ付け機能を検証する．

    タグのPUT後にGETして値が一致することを確認する．

    Args:
        client: S3クライアント．
        bucket: バケット名．
        key: 検証対象オブジェクトキー．
        storage: バックエンド識別子．

    Returns:
        機能検証結果．
    """
    try:
        client.put_object_tagging(
            Bucket=bucket,
            Key=key,
            Tagging={"TagSet": [{"Key": "env", "Value": "test"}]},
        )
        resp = client.get_object_tagging(Bucket=bucket, Key=key)
        found = any(
            t["Key"] == "env" and t["Value"] == "test" for t in resp.get("TagSet", [])
        )
        return FeatureResult(storage, "TAGGING", found, None)
    except Exception as e:
        return FeatureResult(storage, "TAGGING", False, str(e))


def validate_bucket_policy(
    client: S3Client,
    bucket: str,
    storage: str,
) -> FeatureResult:
    """バケットポリシーの設定・取得を検証する．

    公開読み取りポリシーをPUTしてGETで内容が一致することを確認する．

    Args:
        client: S3クライアント．
        bucket: バケット名．
        storage: バックエンド識別子．

    Returns:
        機能検証結果．
    """
    policy = {
        "Version": "2012-10-17",
        "Statement": [
            {
                "Effect": "Allow",
                "Principal": {"AWS": "*"},
                "Action": "s3:GetObject",
                "Resource": f"arn:aws:s3:::{bucket}/*",
            }
        ],
    }
    try:
        client.put_bucket_policy(Bucket=bucket, Policy=json.dumps(policy))
        resp = client.get_bucket_policy(Bucket=bucket)
        got = json.loads(resp["Policy"])
        ok = got["Statement"][0]["Effect"] == "Allow"
        return FeatureResult(storage, "BUCKET_POLICY", ok, None)
    except Exception as e:
        return FeatureResult(storage, "BUCKET_POLICY", False, str(e))


def validate_acl(
    client: S3Client,
    bucket: str,
    storage: str,
) -> FeatureResult:
    """バケットACLの設定・取得を検証する．

    private ACLをPUTしてGETでOwner情報が返ることを確認する．

    Args:
        client: S3クライアント．
        bucket: バケット名．
        storage: バックエンド識別子．

    Returns:
        機能検証結果．
    """
    try:
        client.put_bucket_acl(Bucket=bucket, ACL="private")
        resp = client.get_bucket_acl(Bucket=bucket)
        owner = resp.get("Owner", {})
        ok = bool(owner.get("DisplayName") or owner.get("ID"))
        return FeatureResult(storage, "ACL", ok, None)
    except Exception as e:
        return FeatureResult(storage, "ACL", False, str(e))


def run_feature_validation(
    client: S3Client,
    bucket: str,
    storage: str,
) -> list[FeatureResult]:
    """全機能検証（HEAD・TAGGING・BUCKET_POLICY・ACL）を実行する．

    プローブオブジェクトをアップロードして各検証を実行し，最後に削除する．

    Args:
        client: S3クライアント．
        bucket: バケット名．
        storage: バックエンド識別子．

    Returns:
        機能検証結果リスト．
    """
    client.put_object(Bucket=bucket, Key=_PROBE_KEY, Body=b"\x00" * _PROBE_SIZE)
    results = [
        validate_head(client, bucket, _PROBE_KEY, _PROBE_SIZE, storage),
        validate_tagging(client, bucket, _PROBE_KEY, storage),
        validate_bucket_policy(client, bucket, storage),
        validate_acl(client, bucket, storage),
    ]
    client.delete_object(Bucket=bucket, Key=_PROBE_KEY)
    return results


# ── 結果保存 ────────────────────────────────────────────────────────────────


def save_results(
    op_results: list[OperationResult],
    feat_results: list[FeatureResult],
    out_dir: Path,
) -> None:
    """計測結果をCSVファイルへ書き出す．

    Args:
        op_results: オペレーション計測結果リスト．
        feat_results: 機能検証結果リスト．
        out_dir: 出力先ディレクトリ．存在しない場合は作成する．
    """
    out_dir.mkdir(parents=True, exist_ok=True)
    if op_results:
        pl.DataFrame([vars(r) for r in op_results]).write_csv(
            out_dir / "op_results.csv"
        )
    if feat_results:
        pl.DataFrame([vars(r) for r in feat_results]).write_csv(
            out_dir / "feature_results.csv"
        )


# ── ベンチマーク実行 ────────────────────────────────────────────────────────


def benchmark_storage(
    workload_config: WorkloadConfig,
    storage_config: StorageConfig,
    data_dir: Path,
    results_dir: Path,
) -> None:
    """単一ストレージバックエンドに対してベンチマークを実行する．

    バケットのセットアップ・計測・機能検証・結果保存・バケット削除を行う．

    Args:
        workload_config: ワークロードパラメータ．
        storage_config: 対象ストレージの接続設定．
        data_dir: テスト用Parquetファイルが格納されたディレクトリ．
        results_dir: 結果CSVの出力先ディレクトリ．
    """
    client = create_client(storage_config)
    bucket = storage_config.bucket
    setup_bucket(client, bucket)
    try:
        op_results = run_operation_measurement(
            client, bucket, workload_config, storage_config.name, data_dir
        )
        feat_results = run_feature_validation(client, bucket, storage_config.name)
        save_results(op_results, feat_results, results_dir / storage_config.name)
    finally:
        teardown_bucket(client, bucket)


# ── エントリーポイント ──────────────────────────────────────────────────────


_ALL_STORAGE_CONFIGS = {
    "minio": minio.get_config,
    "seaweedfs": seaweedfs.get_config,
    "garage": garage.get_config,
}


def main() -> None:
    """ベンチマークのエントリーポイント．

    --storage で指定したバックエンドについて，小ファイル・大ファイル両ワークロードを計測する．
    """
    print("Start Benchmark")
    parser = argparse.ArgumentParser(
        description="S3互換オブジェクトストレージベンチマーク"
    )
    parser.add_argument(
        "--storage",
        choices=list(_ALL_STORAGE_CONFIGS),
        required=True,
        help="計測対象のストレージバックエンド",
    )
    parser.add_argument(
        "--out-dir",
        type=Path,
        default=Path("./results/trial1"),
        help="結果の出力先ディレクトリ (デフォルト: ./trial1)",
    )
    args = parser.parse_args()

    storage_config = _ALL_STORAGE_CONFIGS[args.storage]()
    workload_configs = [
        WorkloadConfig(name="small", file_mb=1, n_file=1_000, n_trial=10),
        WorkloadConfig(name="large", file_mb=100, n_file=10, n_trial=10),
    ]
    print(f"ベンチマーク設定: {workload_configs}")

    for wl in workload_configs:
        data_dir = args.out_dir / wl.name / "data"
        # 既存データがあれば再生成しない（再実行時の時間節約）
        if not data_dir.exists():
            generate_parquet_file(
                output_dir=data_dir, n_file=wl.n_file, target_mb=wl.file_mb
            )

        results_dir = args.out_dir / wl.name / "results"
        benchmark_storage(wl, storage_config, data_dir, results_dir)


if __name__ == "__main__":
    main()
