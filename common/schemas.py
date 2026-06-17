from datetime import datetime
from typing import Optional, List
from pydantic import BaseModel, Field


class PhotoUploadResponse(BaseModel):
    id: int
    camera_id: str
    filename: str
    status: str
    created_at: datetime
    minio_object_key: str

    class Config:
        from_attributes = True


class PhotoQuery(BaseModel):
    camera_id: Optional[str] = None
    status: Optional[str] = None
    category: Optional[str] = None
    has_animal: Optional[bool] = None
    min_confidence: Optional[float] = None
    max_confidence: Optional[float] = None
    start_time: Optional[datetime] = None
    end_time: Optional[datetime] = None
    skip: int = Field(default=0, ge=0)
    limit: int = Field(default=100, ge=1, le=1000)


class DetectionResult(BaseModel):
    class_name: str
    confidence: float
    bbox_x1: Optional[float] = None
    bbox_y1: Optional[float] = None
    bbox_x2: Optional[float] = None
    bbox_y2: Optional[float] = None


class PhotoDetail(BaseModel):
    id: int
    camera_id: str
    filename: str
    content_type: str
    file_size: int
    minio_bucket: str
    minio_object_key: str
    source_channel: str
    status: str
    category: str
    has_animal: Optional[bool]
    confidence: Optional[float]
    detected_classes: Optional[str]
    width: Optional[int]
    height: Optional[int]
    captured_at: Optional[datetime]
    created_at: datetime
    updated_at: datetime
    detections: List[DetectionResult] = []

    class Config:
        from_attributes = True


class StatsResponse(BaseModel):
    total_photos: int
    pending_count: int
    empty_count: int
    animal_count: int
    unknown_count: int
    failed_count: int
