#!/usr/bin/env bash
# MinIOコンテナを起動する
set -euo pipefail

CONTAINER_NAME="minio"
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"

# 他のストレージコンテナを停止してディスクを解放する
"$SCRIPT_DIR/stop_all.sh"

if podman container exists "$CONTAINER_NAME" 2>/dev/null; then
    echo "既存コンテナ '$CONTAINER_NAME' を削除します"
    podman rm -f -v "$CONTAINER_NAME"
fi

podman run -d \
    --name "$CONTAINER_NAME" \
    -p 9000:9000 \
    -p 9001:9001 \
    -e MINIO_ROOT_USER=minioadmin \
    -e MINIO_ROOT_PASSWORD=minioadmin \
    quay.io/minio/minio:RELEASE.2025-09-07T16-13-09Z server /data --console-address ":9001"

echo "MinIO 起動待機中..."
until podman exec "$CONTAINER_NAME" mc ready local 2>/dev/null; do
    sleep 1
done

echo "MinIO 準備完了"
echo "  API:     http://localhost:9000"
echo "  Console: http://localhost:9001"
