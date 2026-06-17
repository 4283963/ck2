from pydantic_settings import BaseSettings, SettingsConfigDict
from typing import Optional, List
from pathlib import Path


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=True,
    )

    MYSQL_HOST: str = "127.0.0.1"
    MYSQL_PORT: int = 3306
    MYSQL_USER: str = "ck2_user"
    MYSQL_PASSWORD: str = "ck2_pass_2024"
    MYSQL_DATABASE: str = "camera_photos"

    MINIO_HOST: str = "127.0.0.1"
    MINIO_PORT: int = 9000
    MINIO_ROOT_USER: str = "ck2minioadmin"
    MINIO_ROOT_PASSWORD: str = "ck2minioadmin2024"
    MINIO_SECURE: bool = False
    MINIO_BUCKET: str = "camera-photos"

    MQTT_HOST: str = "127.0.0.1"
    MQTT_PORT: int = 1883
    MQTT_USERNAME: Optional[str] = None
    MQTT_PASSWORD: Optional[str] = None
    MQTT_TOPIC: str = "camera/+/photo"

    INGESTION_SERVICE_HOST: str = "0.0.0.0"
    INGESTION_SERVICE_PORT: int = 8000
    INGESTION_LOG_LEVEL: str = "INFO"

    DETECTION_SERVICE_HOST: str = "0.0.0.0"
    DETECTION_SERVICE_PORT: int = 8001
    DETECTION_LOG_LEVEL: str = "INFO"
    CONFIDENCE_THRESHOLD: float = 0.3
    EMPTY_PHOTO_THRESHOLD: float = 0.3
    YOLO_MODEL_PATH: str = "yolov8n.pt"
    DETECTION_POLL_INTERVAL: int = 5
    DETECTION_BATCH_SIZE: int = 10
    DETECTION_ANIMAL_CLASSES: str = "bird,cat,dog,horse,sheep,cow,elephant,bear,zebra,giraffe"

    @property
    def database_url(self) -> str:
        return (
            f"mysql+pymysql://{self.MYSQL_USER}:{self.MYSQL_PASSWORD}"
            f"@{self.MYSQL_HOST}:{self.MYSQL_PORT}/{self.MYSQL_DATABASE}?charset=utf8mb4"
        )

    @property
    def minio_endpoint(self) -> str:
        return f"{self.MINIO_HOST}:{self.MINIO_PORT}"

    @property
    def animal_class_list(self) -> List[str]:
        return [c.strip() for c in self.DETECTION_ANIMAL_CLASSES.split(",") if c.strip()]


settings = Settings()
