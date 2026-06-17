import enum
from datetime import datetime
from sqlalchemy import Column, Integer, String, DateTime, Text, Float, Boolean, ForeignKey, Index
from sqlalchemy.orm import relationship
from common.database import Base


class PhotoStatus(str, enum.Enum):
    PENDING = "pending"
    DETECTING = "detecting"
    COMPLETED = "completed"
    FAILED = "failed"


class PhotoCategory(str, enum.Enum):
    UNKNOWN = "unknown"
    EMPTY = "empty"
    ANIMAL = "animal"


class Photo(Base):
    __tablename__ = "photos"

    id = Column(Integer, primary_key=True, autoincrement=True, index=True)
    camera_id = Column(String(64), nullable=False, index=True)
    filename = Column(String(255), nullable=False)
    content_type = Column(String(64), nullable=False)
    file_size = Column(Integer, nullable=False)
    minio_bucket = Column(String(128), nullable=False)
    minio_object_key = Column(String(512), nullable=False)
    source_channel = Column(String(32), nullable=False, default="http")
    mqtt_topic = Column(String(512), nullable=True)
    status = Column(String(32), nullable=False, default=PhotoStatus.PENDING.value, index=True)
    category = Column(String(32), nullable=False, default=PhotoCategory.UNKNOWN.value, index=True)
    has_animal = Column(Boolean, nullable=True)
    confidence = Column(Float, nullable=True)
    detected_classes = Column(Text, nullable=True)
    width = Column(Integer, nullable=True)
    height = Column(Integer, nullable=True)
    captured_at = Column(DateTime, nullable=True, index=True)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow, index=True)
    updated_at = Column(DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)

    detections = relationship("Detection", back_populates="photo", cascade="all, delete-orphan")

    __table_args__ = (
        Index("idx_camera_created", "camera_id", "created_at"),
        Index("idx_status_category", "status", "category"),
    )


class Detection(Base):
    __tablename__ = "detections"

    id = Column(Integer, primary_key=True, autoincrement=True, index=True)
    photo_id = Column(Integer, ForeignKey("photos.id", ondelete="CASCADE"), nullable=False, index=True)
    class_name = Column(String(64), nullable=False, index=True)
    confidence = Column(Float, nullable=False)
    bbox_x1 = Column(Float, nullable=True)
    bbox_y1 = Column(Float, nullable=True)
    bbox_x2 = Column(Float, nullable=True)
    bbox_y2 = Column(Float, nullable=True)
    model_name = Column(String(128), nullable=True)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)

    photo = relationship("Photo", back_populates="detections")
