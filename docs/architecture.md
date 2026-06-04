# benchmark.py — コーディング全体像

## モジュール構成

```
src/
├── benchmark.py      # ベンチマーク本体（計測・検証・保存・エントリーポイント）
├──
└── generate_data.py  # テスト用 Parquet ファイルの生成
```

`benchmark.py` が `generate_data.generate_parquet_file` をインポートし，実行前にローカルデータを用意する．

---

## データクラス

| クラス            | 役割                                 | 主なフィールド                                                                                    |
| ----------------- | ------------------------------------ | ------------------------------------------------------------------------------------------------- |
| `WorkloadConfig`  | ワークロードの条件を設定             | `name`, `file_mb`, `n_file`, `n_trial`                                                            |
| `StorageConfig`   | S3互換エンドポイントの接続設定       | `name`, `endpoint_url`, `access_key`, `secret_key`, `bucket`                                      |
| `OperationResult` | PUT / GET / DELETE 1回分の計測値     | `storage`, `operation`, `workload`, `trial`, `key`, `size_bytes`, `elapsed_ms`, `throughput_mbps` |
| `FeatureResult`   | HEAD・タグ・ポリシー・ACL の検証結果 | `storage`, `feature`, `supported`, `error`                                                        |

---

## エントリーポイントと全体フロー

```
main()
  ├─ WorkloadConfig を定義
  ├─ 3ストレージ分の StorageConfig を定義
  ├─ generate_parquet_file() でローカルデータを生成
  └─ for storage in storage_list:
          benchmark_storage(...)    # ベンチマーク測定
```

---

## ベンチマーク測定の内容

```
benchmark_storage()
 ├─ create_client()
 ├─ setup_bucket()
 ├─ run_operation_measurement() -> list[OperationResult]
 ├─ run_feature_validation() -> list[FeatureResult]
 ├─ save_results()
 └─ teardown_bucket()
```

## 関数グループとデータフロー

### 1. クライアント・バケット管理

```
create_client(config) -> S3Client
setup_bucket(client, bucket) -> None   # バケット未存在なら作成
teardown_bucket(client, bucket) -> None # 全オブジェクト削除 → バケット削除
```

### 2. 単一オペレーション計測

各関数は1回の操作を `time` 等で囲み，`elapsed_ms` と `throughput_mbps` を算出して `OperationResult` を返す．

```
# 下記3つをまとめて呼び出すラッパー
run_operation_measurement()
# 各オペレーション計測
measure_put() -> OperationResult
measure_get() -> OperationResult
measure_delete() -> OperationResult
```

### 3. 機能検証

各関数は1回の操作で検証を行い， `FeatureResult` を返す．

検証項目

- HEADリクエスト
- オブジェクトタグ
- バケットACL
-

```
# 下記4つをまとめて呼び出すラッパー
run_feature_validation(client, ...)               -> list[FeatureResult]
# 各機能評価
validate_head()       -> FeatureResult
validate_tagging()    -> FeatureResult
validate_bucket_policy()   -> FeatureResult
validate_acl()             -> FeatureResult
```

### 4. 結果保存

```
# op_results.csv と feature_results.csv を out_dir に書き出す
save_results() → None
```

---
