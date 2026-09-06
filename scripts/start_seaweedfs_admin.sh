#!/usr/bin/env bash
# SeaweedFSの管理UI（weed admin）を起動する
#
# weed admin は weed server に含まれない独立したコマンドのため，
# 計測用コンテナとは別プロセスとして起動する必要がある．
# 計測結果に影響を与えないよう，ベンチマーク実行時は起動しない．
set -euo pipefail

CONTAINER_NAME="seaweedfs"
ADMIN_PORT=23646

if ! podman container exists "$CONTAINER_NAME" 2>/dev/null; then
    echo "エラー: コンテナ '$CONTAINER_NAME' が起動していない．先に ./scripts/start_seaweedfs.sh を実行する" >&2
    exit 1
fi

podman exec -d "$CONTAINER_NAME" \
    weed admin -port="$ADMIN_PORT" -master=localhost:9333 -dataDir=/tmp/admin

echo "管理UI 起動待機中..."
until curl -s -o /dev/null "http://localhost:$ADMIN_PORT" 2>/dev/null; do
    sleep 1
done

echo "SeaweedFS 管理UI 準備完了"
echo "  Admin UI: http://localhost:$ADMIN_PORT"
echo "  ポリシー: http://localhost:$ADMIN_PORT/object-store/policies"
