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
    group_id: Optional[int] = None
    exclude_group_id: Optional[int] = None
    skip: int = Field(default=0, ge=0)
    limit: int = Field(default=100, ge=1, le=1000)


class DetectionResult(BaseModel):
    class_name: str
    confidence: float
    bbox_x1: Optional[float] = None
    bbox_y1: Optional[float] = None
    bbox_x2: Optional[float] = None
    bbox_y2: Optional[float] = None


class GroupBrief(BaseModel):
    id: int
    name: str
    group_type: str
    color: Optional[str] = None

    class Config:
        from_attributes = True


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
    groups: List[GroupBrief] = []

    class Config:
        from_attributes = True


class StatsResponse(BaseModel):
    total_photos: int
    pending_count: int
    empty_count: int
    animal_count: int
    unknown_count: int
    failed_count: int


class GroupCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=128, description="组别名称，唯一")
    group_type: str = Field(default="custom", description="类型: area(区域) / tag(标签) / custom(自定义)")
    description: Optional[str] = Field(default=None, max_length=2000, description="组别描述")
    color: Optional[str] = Field(default=None, max_length=16, description="标签颜色，如 #FF5733")
    cover_photo_id: Optional[int] = Field(default=None, description="封面照片ID")
    sort_order: int = Field(default=0, description="排序序号，小的在前")


class GroupUpdate(BaseModel):
    name: Optional[str] = Field(default=None, min_length=1, max_length=128)
    group_type: Optional[str] = None
    description: Optional[str] = None
    color: Optional[str] = None
    cover_photo_id: Optional[int] = None
    sort_order: Optional[int] = None


class GroupDetail(BaseModel):
    id: int
    name: str
    group_type: str
    description: Optional[str]
    color: Optional[str]
    cover_photo_id: Optional[int]
    sort_order: int
    created_at: datetime
    updated_at: datetime
    photo_count: int = 0

    class Config:
        from_attributes = True


class PhotoIdsRequest(BaseModel):
    photo_ids: List[int] = Field(..., min_length=1, max_length=500, description="照片ID列表")


class GroupBatchAddResponse(BaseModel):
    group_id: int
    group_name: str
    added_count: int
    skipped_count: int
    added_ids: List[int]
    skipped_ids: List[int]


class GroupBatchRemoveResponse(BaseModel):
    group_id: int
    group_name: str
    removed_count: int

