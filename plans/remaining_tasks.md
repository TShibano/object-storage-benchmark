# 計画書(残タスク)

計画1〜6（環境構築・データ生成・スクリプト実装・3ストレージの計測）は完了済み．
本書は `plans/overview.md` の 7・8 を含む残作業を整理したもの．

## 進捗（2026-09-06 時点）

Step 1〜3 は完了．Step 4（WebUI目視検証）・Step 5（結論）が残っている．

計測はコンテナイメージのタグを固定してやり直し，**`results/trial2/` を正とする**．
trial1 はタグ未固定で性能データと機能検証データのバージョンが揃っていないため，
履歴として残すのみでレポートには使わない．

| ストレージ | 固定タグ |
| ---------- | -------- |
| MinIO | `quay.io/minio/minio:RELEASE.2025-09-07T16-13-09Z`（OSS版の最終リリース） |
| SeaweedFS | `chrislusf/seaweedfs:4.45` |
| Garage | `dxflrs/garage:v2.3.0` |

再実行の過程で判明した不具合と対処．

- `podman rm` に `-v` がなく，イメージが宣言する匿名ボリュームが残り続けていた．
  計測のたびに数GB蓄積し，podman VMのディスクを枯渇させてPUTがInternalErrorで
  失敗する原因になっていた．全スクリプトに `-v` を追加して解消
- Garage v2系ではS3 DeleteBucketが実際に成功するため，`teardown_bucket` が
  事前作成したバケットを消してしまい後続ワークロードが失敗していた．
  バケットは残しオブジェクトのみ削除する方針に変更
- SeaweedFSはボリューム上限が既定4（計2GB）で小ファイルワークロードに足りず，
  起動待機もmasterの応答のみで不十分だった．`-volume.max=60` と待機処理を追加
- ワークロード毎にコンテナを作り直せるよう `--workload` を追加

## 現状サマリ

- 計測結果は `results/trial1/` に格納済み（`.gitignore` 対象のため VCS 管理外）
  - small: 1 MB × 1,000ファイル × 10トライアル → 各ストレージ 30,000行
  - large: 100 MB × 10ファイル × 10トライアル → 各ストレージ 300行
  - 3ストレージ（MinIO・SeaweedFS・Garage）× 2ワークロードすべて揃っている
- 機能検証結果は `feature_results.csv` に記録済み
- 未着手: グラフ生成・WebUI目視検証・結論

---

## Step 1: 作業ツリーの整理

計測実行時の残骸と複数の論理変更が1つの change に混在しているため，先に整理する．

- [x] `.gitignore` に `.DS_Store` を追加し，追跡対象から外す
- [x] `trial1/`（トップレベル）を削除する
      - テスト実行時の残骸（`results_test`・`results_test2`）であり，本番結果は `results/trial1/` 側
      - 1 MB超のparquetが1,000件あり，`jj` がスナップショットを拒否する警告を毎回出している
- [x] 現在の change `ypmxsopr`（"ベンチマーク実行"）を論理単位に分割する
      - `scripts/*`: stop_all.sh の呼び出し追加・Garage の rpc 設定修正・SeaweedFS の volumeSizeLimitMB 追加
      - `src/*`: StorageConfig への region 追加・チェックサム無効化・teardown の例外緩和

**完了条件**: `jj st` が警告なしでクリーンに表示され，各 change が単一の論理変更になっている．

---

## Step 2: 分析前の不具合修正・再検証

グラフと結論を作り直さずに済むよう，分析より先に対応する．

- [x] **DELETE のスループットが無意味な値になっている**
      - `src/benchmark.py` の `measure_delete` がボディ転送のない DELETE に対して
        `size_bytes / elapsed` を計算しており，77,000 MB/s 等の値になる
      - 方針: DELETE はレイテンシのみを指標とし，グラフ・集計から除外する
        （`throughput_mbps` を `None` にするか，分析側でフィルタするかは実装時に決める）
- [x] **Garage の HEAD が false（エラーメッセージは空）**
      - `src/benchmark.py` の `validate_head` が `ContentType is not None` を成功条件に含めているが，
        `docs/benchmark_spec.md` の成功条件は「ClientError が発生せず ContentLength が一致する」
      - 判定が仕様より厳しく，「HEAD 非対応」と誤記録している可能性が高い
      - 対応: 判定を仕様に合わせ，Garage コンテナを起動して機能検証のみ再実行して確認する
- [x] **SeaweedFS の BUCKET_POLICY が MalformedPolicy**
      - `Policy has invalid resource.` というエラー．Resource の ARN 表記の差異の可能性がある
      - 実装差（本当に非対応）なのかスクリプト側の問題なのかを切り分け，結論に正しく反映する

**完了条件**: 修正後の機能検証結果が `results/` に反映され，各 false の理由が実装差だと確認できている．

---

## Step 3: グラフ生成スクリプト（overview 計画 7）

- [x] `matplotlib` を `pyproject.toml` の依存に追加する（現在未追加）
- [x] `src/analyze.py` を新規作成
      - 入力: `results/trial1/{small,large}/results/{storage}/op_results.csv`
      - 集計: `docs/benchmark_spec.md` に従い P50 / P95 / P99 レイテンシ，平均・最大・最小スループット
      - 出力: 集計CSV とグラフ画像
- [x] グラフの内容
      - ワークロード別・オペレーション別のレイテンシ比較（3ストレージ横並び）
      - PUT / GET のスループット比較（DELETE は Step 2 の方針に従い除外）
      - 機能検証結果の一覧表

**完了条件**: スクリプト1回の実行でグラフ一式が再生成できる．

---

## Step 4: WebUI 目視検証

`docs/benchmark_spec.md` の「4. WebUI 目視検証」に沿って手動で実施する．

- [x] 各ストレージのコンテナを起動し管理コンソールにアクセス
      - MinIO: `http://localhost:9001`
      - SeaweedFS: `http://localhost:9333`（Filer: `http://localhost:8888`）
      - Garage: `http://localhost:3900`
- [x] 8項目（アクセス可否・バケット一覧・オブジェクト閲覧・アップロード・ダウンロード・
      バケットポリシー設定・メトリクス・使いやすさ）を確認
- [x] `webui_results.csv` に手入力で記録する

**完了条件**: 3ストレージ分の記録が `webui_results.csv` に揃っている．

---

## Step 5: 結論（overview 計画 8）

- [x] README に比較表を追加
      - パフォーマンス（レイテンシ・スループット）
      - S3 API 機能対応状況
      - WebUI 評価
- [x] 移行先の推奨と，その判断理由を記述する
- [x] 計測環境に起因する制約（同一ホスト・シリアル実行・ウォームアップなし）を明記する

**完了条件**: README だけを読めば移行先の判断根拠が追える状態になっている．
