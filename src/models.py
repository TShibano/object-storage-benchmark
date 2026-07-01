"""
S3互換オブジェクトストレージベンチマーク共通データクラス
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class WorkloadConfig:
    """ワークロードのパラメータ設定．

    Attributes:
        name: ワークロード識別子．"small" または "large"．
        file_mb: 1ファイルのサイズ (MB)．
        n_file: 計測対象ファイル数．
        n_trial: 繰り返し試行回数．
    """

    name: str
    file_mb: int
    n_file: int
    n_trial: int


@dataclass
class StorageConfig:
    """ストレージバックエンドの接続設定．

    Attributes:
        name: バックエンド識別子．"minio"・"seaweedfs"・"garage" のいずれか．
        endpoint_url: S3互換エンドポイントURL．
        access_key: アクセスキー．
        secret_key: シークレットキー．
        bucket: 使用バケット名．
    """

    name: str
    endpoint_url: str
    access_key: str
    secret_key: str
    bucket: str


@dataclass
class OperationResult:
    """1回のS3オペレーション計測結果．

    Attributes:
        storage: バックエンド識別子．
        operation: オペレーション種別．"PUT"・"GET"・"DELETE" のいずれか．
        workload: ワークロード識別子．
        trial: 試行番号 (0-indexed)．
        key: オブジェクトキー．
        size_bytes: オブジェクトサイズ (bytes)．
        elapsed_ms: 所要時間 (ms)．
        throughput_mbps: スループット (MB/s)．
    """

    storage: str
    operation: str
    workload: str
    trial: int
    key: str
    size_bytes: int
    elapsed_ms: float
    throughput_mbps: float


@dataclass
class FeatureResult:
    """S3機能検証の結果．

    Attributes:
        storage: バックエンド識別子．
        feature: 検証した機能名．"HEAD"・"TAGGING"・"BUCKET_POLICY"・"ACL" のいずれか．
        supported: サポートされているか否か．
        error: 失敗時のエラーメッセージ．成功時は None．
    """

    storage: str
    feature: str
    supported: bool
    error: str | None
