#!/usr/bin/env bash
# SeaweedFSコンテナを起動する
set -euo pipefail

CONTAINER_NAME="seaweedfs"
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"

# 他のストレージコンテナを停止してディスクを解放する
"$SCRIPT_DIR/stop_all.sh"

if podman container exists "$CONTAINER_NAME" 2>/dev/null; then
    echo "既存コンテナ '$CONTAINER_NAME' を削除します"
    podman rm -f -v "$CONTAINER_NAME"
fi

podman run -d \
    --name "$CONTAINER_NAME" \
    -p 9333:9333 \
    -p 8081:8080 \
    -p 8888:8888 \
    -p 8333:8333 \
    chrislusf/seaweedfs:4.45 server \
    -s3 \
    -s3.port=8333 \
    -filer \
    -filer.port=8888 \
    -master.volumeSizeLimitMB=500 \
    -volume.max=60

echo "SeaweedFS 起動待機中..."
until curl -sf "http://localhost:9333/cluster/status" > /dev/null 2>&1; do
    sleep 1
done

# masterが応答してもボリュームサーバの登録前はPUTがInternalErrorになるため，
# 実際に書き込み先を割り当てられる状態まで待つ
echo "ボリューム準備待機中..."
until curl -s "http://localhost:9333/dir/assign" | grep -q '"fid"'; do
    sleep 1
done

# S3 APIはmasterより遅れて起動するため個別に待つ
echo "S3 API待機中..."
until curl -s -o /dev/null "http://localhost:8333"; do
    sleep 1
done

echo "SeaweedFS 準備完了"
echo "  Master: http://localhost:9333"
echo "  S3:     http://localhost:8333"
echo "  Filer:  http://localhost:8888"
