import os
import uuid
import base64
import logging
from datetime import datetime
from typing import Optional, Tuple
from PIL import Image
import io

from sqlalchemy.orm import Session

from common.config import settings
from common.models import Photo, PhotoStatus, PhotoCategory
from ingestion_service.storage import get_minio_storage

logger = logging.getLogger(__name__)

ALLOWED_CONTENT_TYPES = {
    "image/jpeg": ".jpg",
    "image/png": ".png",
    "image/gif": ".gif",
    "image/webp": ".webp",
    "image/bmp": ".bmp",
}


def get_image_extension(content_type: str) -> str:
    return ALLOWED_CONTENT_TYPES.get(content_type, ".jpg")


def is_valid_content_type(content_type: str) -> bool:
    return content_type.lower() in ALLOWED_CONTENT_TYPES


def generate_object_key(camera_id: str, content_type: str) -> str:
    now = datetime.utcnow()
    ext = get_image_extension(content_type)
    year = now.strftime("%Y")
    month = now.strftime("%m")
    day = now.strftime("%d")
    unique_id = uuid.uuid4().hex[:12]
    return f"{camera_id}/{year}/{month}/{day}/{unique_id}{ext}"


def get_image_dimensions(image_bytes: bytes) -> Tuple[Optional[int], Optional[int]]:
    try:
        with Image.open(io.BytesIO(image_bytes)) as img:
            return img.width, img.height
    except Exception as e:
        logger.warning(f"Failed to get image dimensions: {e}")
        return None, None


def save_photo_to_db(
    db: Session,
    camera_id: str,
    filename: str,
    content_type: str,
    image_bytes: bytes,
    source_channel: str,
    mqtt_topic: Optional[str] = None,
    captured_at: Optional[datetime] = None,
) -> Photo:
    object_key = generate_object_key(camera_id, content_type)
    storage = get_minio_storage()
    bucket, key = storage.upload_object(object_key, image_bytes, content_type)

    width, height = get_image_dimensions(image_bytes)

    photo = Photo(
        camera_id=camera_id,
        filename=filename,
        content_type=content_type,
        file_size=len(image_bytes),
        minio_bucket=bucket,
        minio_object_key=key,
        source_channel=source_channel,
        mqtt_topic=mqtt_topic,
        status=PhotoStatus.PENDING.value,
        category=PhotoCategory.UNKNOWN.value,
        width=width,
        height=height,
        captured_at=captured_at or datetime.utcnow(),
    )

    db.add(photo)
    db.commit()
    db.refresh(photo)

    logger.info(f"Saved photo id={photo.id}, camera={camera_id}, size={len(image_bytes)} bytes")
    return photo


def parse_base64_image(data: str) -> Tuple[bytes, Optional[str]]:
    try:
        if "," in data:
            header, encoded = data.split(",", 1)
            content_type = None
            if "data:" in header:
                content_type_part = header.split(";")[0]
                content_type = content_type_part.replace("data:", "").strip()
        else:
            encoded = data
            content_type = None

        image_bytes = base64.b64decode(encoded)
        return image_bytes, content_type
    except Exception as e:
        logger.error(f"Failed to parse base64 image: {e}")
        raise ValueError(f"Invalid base64 image data: {e}")


def extract_camera_id_from_topic(topic: str) -> str:
    parts = topic.split("/")
    if len(parts) >= 2:
        return parts[1]
    return "unknown"
