# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## プロジェクト概要

S3互換オブジェクトストレージ（MinIO・SeaweedFS・Garage）のベンチマークを行うPythonプロジェクト．MinIOのEOL対応として移行先を選定する目的．

## 実行環境

- MacBook Air M4
- Podman 5.8.1（Docker互換）
- Python（Polars・boto3）

## ベンチマーク対象

| 対象 | 用途 |
| ---- | ---- |
| MinIO | 比較基準（現行システム） |
| SeaweedFS | 移行候補 |
| Garage | 移行候補 |

## ワークロード

| ワークロード | ファイル形式 | サイズ | 個数 | 操作 |
| :----------: | :----------: | :----: | :--: | ---- |
| 小ファイル | Parquet | 1 MB | 1,000 | PUT / GET / DELETE |
| 大ファイル | Parquet | 100 MB | 10 | PUT / GET / DELETE |

## 計測指標

- スループット (MB/s): 転送時間から算出
- レイテンシ (ms): 各オペレーション所要時間
- 機能検証: HEAD・タグ付け・バケットポリシー・ACL
- UI評価: 管理コンソールを目視評価
