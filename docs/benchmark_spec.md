# benchmark.py — ベンチマーク設計仕様

## 計測環境

| 項目 | 内容 |
| ---- | ---- |
| マシン | MacBook Air M4 |
| コンテナランタイム | Podman 5.8.1（Docker互換） |
| ネットワーク | localhost（コンテナ⇔ホスト間） |
| クライアント | Python / boto3 |
| 対象ストレージ | MinIO（比較基準）・SeaweedFS・Garage |

---

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

## ワークロードパラメータ

| ワークロード | `file_mb` | `n_file` | `n_trial` | 合計データ量 |
| :----------: | :-------: | :------: | :-------: | ----------- |
| small        | 1 MB      | 1,000    | 10        | 1 GB / trial |
| large        | 100 MB    | 10       | 10        | 1 GB / trial |

> small・large ともに 1 trial あたり転送データ量は同じ 1 GB．ファイル数・サイズの違いによるオーバーヘッドの差を比較するのが目的．

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

---

### 2. オペレーション計測

#### 関数構成

```
# 下記3つをまとめて呼び出すラッパー
run_operation_measurement()
# 各オペレーション計測
measure_put() -> OperationResult
measure_get() -> OperationResult
measure_delete() -> OperationResult
```

#### 計測手順（1 ワークロードあたり）

`n_trial` 回のトライアルを繰り返す．1 トライアルの手順は以下のとおり．

1. `n_file` 個の Parquet ファイルをローカルディスクから `bytes` として読み込みメモリへ保持
2. **PUT フェーズ**：全ファイルをキー `{workload}/{trial}/{i}.parquet` でシリアルにアップロード
3. **GET フェーズ**：同キーでシリアルにダウンロード（ダウンロード先は `/dev/null` 相当，ディスク書き込みを除外）
4. **DELETE フェーズ**：同キーでシリアルに削除

> 計測は並列化なし（concurrent=1）のシリアル実行のみとする．

#### 計測タイミング

計測には `time.perf_counter()` を使用する（プロセスウォールタイム）．

| オペレーション | 計測開始 | 計測終了 | `elapsed_ms` の対象範囲 |
| :------------: | -------- | -------- | ----------------------- |
| PUT | `upload_fileobj` 呼び出し直前 | レスポンス受信完了 | TCP送信〜HTTP 200 ACK |
| GET | `get_object` 呼び出し直前 | `Body.read()` 完了 | HTTP GET〜全ボディ受信 |
| DELETE | `delete_object` 呼び出し直前 | レスポンス受信完了 | HTTP DELETE〜HTTP 204 ACK |

#### 算出式

```
elapsed_ms      = (perf_counter_end - perf_counter_start) * 1000
throughput_mbps = (size_bytes / 1024 / 1024) / (elapsed_ms / 1000)
```

#### 事前条件・注意事項

- ファイルデータは計測ループ前にすべてメモリへ読み込み，ローカルI/Oを計測から除外する
- ウォームアップランは設けない（コールドスタート含むリアルな性能を計測する）
- エラー発生時は例外を再送出し，該当 trial の結果は記録しない

#### 集計指標（分析フェーズで算出）

`n_trial × n_file` 件の `OperationResult` を Polars で集計する．

| 指標 | 対象列 |
| ---- | ------ |
| P50 / P95 / P99 レイテンシ (ms) | `elapsed_ms` |
| 平均 / 最大 / 最小 スループット (MB/s) | `throughput_mbps` |
| エラー率 | trial 数に対する欠損 trial の割合 |

---

### 3. 機能検証

#### 関数構成

```
# 下記4つをまとめて呼び出すラッパー
run_feature_validation(client, bucket, key) -> list[FeatureResult]
# 各機能検証
validate_head()          -> FeatureResult
validate_tagging()       -> FeatureResult
validate_bucket_policy() -> FeatureResult
validate_acl()           -> FeatureResult
```

#### 検証の前提

- `run_operation_measurement` 終了後に呼び出す（検証用オブジェクトが存在する状態）
- 専用の検証キー `feature-probe.parquet`（小ファイル 1 MB）を 1 つ PUT してから各検証を実施する
- 例外発生時は `supported=False, error=str(e)` を記録し，後続の検証を継続する

#### 各検証の詳細

**HEAD（`validate_head`）**

| 項目 | 内容 |
| ---- | ---- |
| 目的 | オブジェクトのメタデータ取得が機能するか確認する |
| 操作 | `head_object(Bucket, Key)` |
| 確認内容 | レスポンスに `ContentLength > 0` および `ContentType` が含まれること |
| 成功条件 | `ClientError` が発生せず，`ContentLength` が PUT 時のサイズと一致する |
| 典型的な失敗 | 405 Method Not Allowed，404 Not Found |

**TAGGING（`validate_tagging`）**

| 項目 | 内容 |
| ---- | ---- |
| 目的 | オブジェクトタグの付与・取得が機能するか確認する |
| 操作 | `put_object_tagging(Tagging={'TagSet': [{'Key': 'env', 'Value': 'test'}]})` → `get_object_tagging` |
| 確認内容 | 取得した `TagSet` に付与したキー・バリューが含まれること |
| 成功条件 | `TagSet` が往復して一致する |
| 典型的な失敗 | 501 Not Implemented，403 Forbidden |

**BUCKET_POLICY（`validate_bucket_policy`）**

| 項目 | 内容 |
| ---- | ---- |
| 目的 | バケットポリシーの設定・取得が機能するか確認する |
| 操作 | `put_bucket_policy(Policy=json.dumps(policy_doc))` → `get_bucket_policy` |
| 確認内容 | 取得した Policy JSON をパースし，設定した `Statement` の `Effect` が一致すること |
| 成功条件 | Policy JSON が往復して構造が一致する |
| 典型的な失敗 | 405 Method Not Allowed，501 Not Implemented |

**ACL（`validate_acl`）**

> ACL は AWS S3 で非推奨（2023年以降は Object Ownership 設定で無効化可能）．モダンなアクセス制御の代替手段はバケットポリシー（`validate_bucket_policy` で検証済み）．本項は「S3互換ストレージ間での廃止予定 API の実装差異確認」を目的として残す．

| 項目 | 内容 |
| ---- | ---- |
| 目的 | バケット ACL の設定・取得が機能するか確認する（互換性確認のみ，移行先での利用は推奨しない） |
| 操作 | `put_bucket_acl(ACL='private')` → `get_bucket_acl` |
| 確認内容 | レスポンスに `Owner` 情報が含まれること |
| 成功条件 | `ClientError` が発生せず，`Owner.DisplayName` または `Owner.ID` が返る |
| 典型的な失敗 | 501 Not Implemented，405 Method Not Allowed |

---

### 4. WebUI 目視検証

自動化不可のため，コンテナ起動後にブラウザで手動確認する．結果は `webui_results.csv` に手入力で記録する．

#### 対象 URL（ローカル起動時のデフォルト）

| ストレージ | URL |
| --------- | --- |
| MinIO | `http://localhost:9001` |
| SeaweedFS | `http://localhost:9333` (Filer: `http://localhost:8888`) |
| Garage | `http://localhost:3900` |

#### 検証項目

| 項目 | 確認内容 | 評価 |
| ---- | -------- | ---- |
| アクセス可否 | UIにアクセスできるか（ログイン画面またはダッシュボードが表示される） | Pass / Fail |
| バケット一覧 | 作成済みバケットが一覧表示されるか | Pass / Fail |
| オブジェクト閲覧 | バケット内のオブジェクト（キー・サイズ）が一覧表示されるか | Pass / Fail |
| アップロード | UIからファイルをアップロードできるか | Pass / Fail |
| ダウンロード | UIからファイルをダウンロードできるか | Pass / Fail |
| バケットポリシー設定 | UIからバケットポリシーを設定・参照できるか | Pass / Fail / N/A |
| メトリクス | スループット・リクエスト数などの監視情報が表示されるか | Pass / Fail / N/A |
| 使いやすさ | 操作感・情報密度の主観評価（3段階） | 良い / 普通 / 悪い |

#### 記録フォーマット（`webui_results.csv`）

```
storage, item, result, note
MinIO, アクセス可否, Pass, ""
MinIO, バケット一覧, Pass, ""
...
```

---

### 5. 結果保存（自動）

```
# op_results.csv と feature_results.csv を out_dir に書き出す
save_results() → None
```

| ファイル | 内容 | 列 |
| -------- | ---- | -- |
| `op_results.csv` | PUT / GET / DELETE 全 trial の計測値 | `OperationResult` の全フィールド |
| `feature_results.csv` | 機能検証の結果（ストレージ × 機能） | `FeatureResult` の全フィールド |

---

## 用語定義

| 用語 | 定義 |
| ---- | ---- |
| **ACK** (Acknowledgement) | TCP/HTTP における受信確認応答．本仕様では「サーバーが処理完了を示す HTTP レスポンス（PUT: 200 OK，DELETE: 204 No Content）をクライアントが受け取った時点」を指す． |
| **ACL** (Access Control List) | アクセス制御リスト．バケット・オブジェクトへのアクセス権を「誰に何を許可するか」で定義する仕組み．`private`（所有者のみ）・`public-read`（誰でも読み取り可）などのプリセットで設定する．AWS S3 では現在非推奨（バケットポリシーへ移行推奨）だが，S3互換ストレージ間の実装差を確認するため検証対象に含める． |
| **バケットポリシー** (Bucket Policy) | バケット単位のアクセス制御を JSON で記述するリソースベースのポリシー．ACL の後継として AWS S3 が推奨する方式．IAM ポリシーと同様の構文（`Effect` / `Principal` / `Action` / `Resource`）を使い，細粒度の権限設定が可能．S3互換ストレージでの実装差を確認するため検証対象に含める． |
| **P50 / P95 / P99** | パーセンタイル値（百分位数）．P50 は全計測値の中央値，P95 は「全計測値の 95% がこの値以下」，P99 は「99% がこの値以下」であることを示す．平均値より外れ値の影響を受けにくく，断続的なレイテンシスパイクの検出に有効． |
| **スループット** (throughput) | 単位時間あたりのデータ転送量（MB/s）．レイテンシとは独立した「帯域利用効率」を示す指標．ファイルサイズが大きいほど高くなる傾向がある． |
| **TTFB** (Time to First Byte) | リクエスト送信からレスポンスの最初の 1 バイトを受信するまでの時間．本仕様の `elapsed_ms` は全ボディ受信完了を終点とするため TTFB より長くなる．現時点では未計測だが，GET の応答性評価で参考になる指標． |
| **Parquet** | Apache Arrow プロジェクト発の列指向バイナリフォーマット．本ベンチマークではテストデータのファイル形式として使用する． |
