import io
import logging
from typing import Tuple
from minio import Minio
from minio.error import S3Error
from common.config import settings

logger = logging.getLogger(__name__)


class MinioStorage:
    def __init__(self):
        self.client = Minio(
            settings.minio_endpoint,
            access_key=settings.MINIO_ROOT_USER,
            secret_key=settings.MINIO_ROOT_PASSWORD,
            secure=settings.MINIO_SECURE,
        )
        self.bucket = settings.MINIO_BUCKET
        self._ensure_bucket()

    def _ensure_bucket(self):
        try:
            if not self.client.bucket_exists(self.bucket):
                self.client.make_bucket(self.bucket)
                logger.info(f"Created MinIO bucket: {self.bucket}")
        except S3Error as e:
            logger.error(f"Failed to create/check bucket {self.bucket}: {e}")
            raise

    def upload_object(
        self,
        object_key: str,
        data: bytes,
        content_type: str = "application/octet-stream",
    ) -> Tuple[str, str]:
        try:
            data_stream = io.BytesIO(data)
            data_length = len(data)
            self.client.put_object(
                bucket_name=self.bucket,
                object_name=object_key,
                data=data_stream,
                length=data_length,
                content_type=content_type,
            )
            logger.debug(f"Uploaded {object_key} ({data_length} bytes) to {self.bucket}")
            return self.bucket, object_key
        except S3Error as e:
            logger.error(f"Failed to upload {object_key}: {e}")
            raise

    def get_object_url(self, object_key: str, expires: int = 3600) -> str:
        try:
            return self.client.presigned_get_object(
                bucket_name=self.bucket,
                object_name=object_key,
            )
        except S3Error as e:
            logger.error(f"Failed to generate presigned URL for {object_key}: {e}")
            raise

    def get_object_bytes(self, object_key: str) -> bytes:
        try:
            response = self.client.get_object(
                bucket_name=self.bucket,
                object_name=object_key,
            )
            data = response.read()
            response.close()
            response.release_conn()
            return data
        except S3Error as e:
            logger.error(f"Failed to get object {object_key}: {e}")
            raise

    def delete_object(self, object_key: str):
        try:
            self.client.remove_object(bucket_name=self.bucket, object_name=object_key)
            logger.info(f"Deleted {object_key} from {self.bucket}")
        except S3Error as e:
            logger.error(f"Failed to delete {object_key}: {e}")
            raise


minio_storage = None


def get_minio_storage() -> MinioStorage:
    global minio_storage
    if minio_storage is None:
        minio_storage = MinioStorage()
    return minio_storage
