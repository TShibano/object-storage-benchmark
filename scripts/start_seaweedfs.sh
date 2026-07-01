#!/usr/bin/env bash
# SeaweedFSコンテナを起動する
set -euo pipefail

CONTAINER_NAME="seaweedfs"

if podman container exists "$CONTAINER_NAME" 2>/dev/null; then
    echo "既存コンテナ '$CONTAINER_NAME' を削除します"
    podman rm -f "$CONTAINER_NAME"
fi

podman run -d \
    --name "$CONTAINER_NAME" \
    -p 9333:9333 \
    -p 8080:8080 \
    -p 8888:8888 \
    -p 8333:8333 \
    chrislusf/seaweedfs server \
    -s3 \
    -s3.port=8333 \
    -filer \
    -filer.port=8888

echo "SeaweedFS 起動待機中..."
until curl -sf "http://localhost:9333/cluster/status" > /dev/null 2>&1; do
    sleep 1
done

echo "SeaweedFS 準備完了"
echo "  Master: http://localhost:9333"
echo "  S3:     http://localhost:8333"
echo "  Filer:  http://localhost:8888"
