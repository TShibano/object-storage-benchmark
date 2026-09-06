#!/usr/bin/env bash
# WebUI目視検証用に，起動中のストレージへサンプルオブジェクトを投入する
# 使い方: ./scripts/seed_ui_data.sh {minio|seaweedfs|garage}
set -euo pipefail

STORAGE="${1:-}"
case "$STORAGE" in
    minio|seaweedfs|garage) ;;
    *) echo "使い方: $0 {minio|seaweedfs|garage}" >&2; exit 1 ;;
esac

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJ_DIR="$(dirname "$SCRIPT_DIR")"

# Garageはコンテナ起動時に払い出された鍵を環境変数から読む
if [ "$STORAGE" = "garage" ]; then
    # shellcheck source=/dev/null
    . "$SCRIPT_DIR/.garage_env"
fi

cd "$PROJ_DIR/src"
"$PROJ_DIR/.venv/bin/python" - "$STORAGE" <<'PY'
"""WebUI検証用のサンプルオブジェクトを投入する．"""

import io
import os
import sys

import boto3
import botocore.config

import garage
import minio
import seaweedfs

_CONFIGS = {
    "minio": minio.get_config,
    "seaweedfs": seaweedfs.get_config,
    "garage": garage.get_config,
}

config = _CONFIGS[sys.argv[1]]()
client = boto3.client(
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

try:
    client.create_bucket(Bucket=config.bucket)
except Exception as e:  # 既存バケットや権限差はスキップして続行する
    print(f"バケット作成をスキップ: {e}")

for key, size_mb in [
    ("small/sample-001.parquet", 1),
    ("small/sample-002.parquet", 1),
    ("large/sample-100mb.parquet", 100),
]:
    client.upload_fileobj(io.BytesIO(os.urandom(size_mb * 1024 * 1024)), config.bucket, key)
    print(f"投入: {key} ({size_mb} MB)")

print(f"\n完了: バケット '{config.bucket}' に3件のオブジェクトを投入した")
PY
