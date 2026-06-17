import enum
from datetime import datetime
from sqlalchemy import Column, Integer, String, DateTime, Text, Float, Boolean, ForeignKey, Index, UniqueConstraint
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


class GroupType(str, enum.Enum):
    AREA = "area"
    TAG = "tag"
    CUSTOM = "custom"


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
    photo_groups = relationship("PhotoGroup", back_populates="photo", cascade="all, delete-orphan")
    groups = relationship(
        "Group",
        secondary="photo_groups",
        back_populates="photos",
        viewonly=True,
    )

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


class Group(Base):
    __tablename__ = "groups"

    id = Column(Integer, primary_key=True, autoincrement=True, index=True)
    name = Column(String(128), nullable=False, unique=True, index=True)
    group_type = Column(String(32), nullable=False, default=GroupType.CUSTOM.value, index=True)
    description = Column(Text, nullable=True)
    color = Column(String(16), nullable=True)
    cover_photo_id = Column(Integer, ForeignKey("photos.id", ondelete="SET NULL"), nullable=True)
    sort_order = Column(Integer, nullable=False, default=0)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow, index=True)
    updated_at = Column(DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)

    photo_groups = relationship("PhotoGroup", back_populates="group", cascade="all, delete-orphan")
    photos = relationship(
        "Photo",
        secondary="photo_groups",
        back_populates="groups",
        viewonly=True,
    )
    cover_photo = relationship("Photo", foreign_keys=[cover_photo_id])

    __table_args__ = (
        Index("idx_group_type_order", "group_type", "sort_order"),
    )


class PhotoGroup(Base):
    __tablename__ = "photo_groups"

    id = Column(Integer, primary_key=True, autoincrement=True, index=True)
    photo_id = Column(Integer, ForeignKey("photos.id", ondelete="CASCADE"), nullable=False, index=True)
    group_id = Column(Integer, ForeignKey("groups.id", ondelete="CASCADE"), nullable=False, index=True)
    added_at = Column(DateTime, nullable=False, default=datetime.utcnow, index=True)

    photo = relationship("Photo", back_populates="photo_groups")
    group = relationship("Group", back_populates="photo_groups")

    __table_args__ = (
        UniqueConstraint("photo_id", "group_id", name="uq_photo_group"),
    )
