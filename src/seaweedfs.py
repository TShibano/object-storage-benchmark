"""SeaweedFS接続設定"""

from models import StorageConfig


def get_config() -> StorageConfig:
    """SeaweedFSの接続設定を返す．

    Returns:
        SeaweedFS用の StorageConfig．
    """
    return StorageConfig(
        name="seaweedfs",
        endpoint_url="http://localhost:8333",
        access_key="any",
        secret_key="any",
        bucket="benchmark",
    )
