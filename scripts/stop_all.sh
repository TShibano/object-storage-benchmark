#!/usr/bin/env bash
# 全ストレージコンテナを停止・削除する
set -euo pipefail

for name in minio seaweedfs garage; do
    if podman container exists "$name" 2>/dev/null; then
        podman rm -f "$name"
        echo "$name を停止・削除しました"
    else
        echo "$name は起動していません（スキップ）"
    fi
done
