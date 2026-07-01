"""MinIO接続設定"""

from models import StorageConfig


def get_config() -> StorageConfig:
    """MinIOの接続設定を返す．

    Returns:
        MinIO用の StorageConfig．
    """
    return StorageConfig(
        name="minio",
        endpoint_url="http://localhost:9000",
        access_key="minioadmin",
        secret_key="minioadmin",
        bucket="benchmark",
    )
