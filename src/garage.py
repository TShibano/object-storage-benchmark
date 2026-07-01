"""Garage接続設定

アクセスキーはコンテナ起動後に `garage key create` で取得し，
環境変数 GARAGE_ACCESS_KEY / GARAGE_SECRET_KEY に設定してから実行する．
"""

import os

from models import StorageConfig


def get_config() -> StorageConfig:
    """Garageの接続設定を返す．

    アクセスキーは環境変数 GARAGE_ACCESS_KEY・GARAGE_SECRET_KEY から取得する．

    Returns:
        Garage用の StorageConfig．

    Raises:
        KeyError: 環境変数が未設定の場合．
    """
    return StorageConfig(
        name="garage",
        endpoint_url="http://localhost:3900",
        access_key=os.environ["GARAGE_ACCESS_KEY"],
        secret_key=os.environ["GARAGE_SECRET_KEY"],
        bucket="benchmark",
    )
