#!/usr/bin/env bash
# Garageコンテナを起動し，レイアウト設定・キー発行・バケット作成を行う
# 実行後に scripts/.garage_env が生成されるので，ベンチマーク前に source する
set -euo pipefail

CONTAINER_NAME="garage"
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
ENV_FILE="$SCRIPT_DIR/.garage_env"

# 他のストレージコンテナを停止してディスクを解放する
"$SCRIPT_DIR/stop_all.sh"

if podman container exists "$CONTAINER_NAME" 2>/dev/null; then
    echo "既存コンテナ '$CONTAINER_NAME' を削除します"
    podman rm -f "$CONTAINER_NAME"
fi

podman run -d \
    --name "$CONTAINER_NAME" \
    -p 3900:3900 \
    -p 3901:3901 \
    -p 3903:3903 \
    -v "$SCRIPT_DIR/garage.toml:/etc/garage.toml:ro" \
    dxflrs/garage:v2.3.0

echo "Garage 起動待機中..."
until podman exec "$CONTAINER_NAME" /garage status > /dev/null 2>&1; do
    sleep 1
done

# シングルノードのレイアウトを設定（node id は <hash>@<addr> 形式なので hash 部分のみ抽出）
NODE_ID=$(podman exec "$CONTAINER_NAME" /garage node id -q 2>/dev/null | awk -F@ '{print $1}')
echo "ノードID: $NODE_ID"

podman exec "$CONTAINER_NAME" /garage layout assign -z dc1 -c 10G "$NODE_ID"
podman exec "$CONTAINER_NAME" /garage layout apply --version 1
echo "クラスタレイアウトを適用しました"

# キーを作成（既存の場合はスキップ）
KEY_OUTPUT=$(podman exec "$CONTAINER_NAME" /garage key create benchmark-key 2>&1)
echo "$KEY_OUTPUT"

ACCESS_KEY=$(echo "$KEY_OUTPUT" | grep -i "key id" | awk '{print $NF}')
SECRET_KEY=$(echo "$KEY_OUTPUT" | grep -i "secret" | awk '{print $NF}')

if [ -z "$ACCESS_KEY" ] || [ -z "$SECRET_KEY" ]; then
    echo ""
    echo "エラー: キーの解析に失敗しました．上記の出力からキーを手動で設定してください:"
    echo "  export GARAGE_ACCESS_KEY=<Key ID>"
    echo "  export GARAGE_SECRET_KEY=<Secret key>"
    exit 1
fi

# バケットを作成してキーにアクセスを付与
podman exec "$CONTAINER_NAME" /garage bucket create benchmark
podman exec "$CONTAINER_NAME" /garage bucket allow --read --write --owner benchmark --key benchmark-key

# 環境変数ファイルを書き出す
cat > "$ENV_FILE" <<EOF
export GARAGE_ACCESS_KEY="$ACCESS_KEY"
export GARAGE_SECRET_KEY="$SECRET_KEY"
EOF

echo ""
echo "Garage 準備完了"
echo "  S3: http://localhost:3900"
echo ""
echo "ベンチマーク実行前に以下を実行してください:"
echo "  source $ENV_FILE"
