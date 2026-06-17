import logging
from typing import List, Optional
from datetime import datetime

from fastapi import FastAPI, Depends, HTTPException, UploadFile, File, Form, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session
from sqlalchemy import func, and_

from common.config import settings
from common.database import get_db, init_db
from common.models import Photo, PhotoStatus, PhotoCategory, Detection
from common.schemas import (
    PhotoUploadResponse,
    PhotoDetail,
    PhotoQuery,
    StatsResponse,
)
from ingestion_service.photo_service import (
    save_photo_to_db,
    is_valid_content_type,
    parse_base64_image,
)
from ingestion_service.mqtt_listener import mqtt_listener
from ingestion_service.storage import get_minio_storage

logging.basicConfig(
    level=getattr(logging, settings.INGESTION_LOG_LEVEL, logging.INFO),
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)

app = FastAPI(
    title="Camera Photo Ingestion Service",
    description="接收相机图片并存储的API服务 (HTTP POST + MQTT)",
    version="1.0.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.on_event("startup")
async def startup_event():
    init_db()
    logger.info("Database initialized")
    get_minio_storage()
    logger.info("MinIO storage initialized")
    try:
        mqtt_listener.start()
    except Exception as e:
        logger.warning(f"MQTT listener failed to start: {e}. Continuing without MQTT.")


@app.on_event("shutdown")
async def shutdown_event():
    mqtt_listener.stop()
    logger.info("MQTT listener stopped")


@app.get("/health")
async def health_check():
    return {
        "status": "healthy",
        "service": "ingestion",
        "timestamp": datetime.utcnow().isoformat(),
    }


@app.post("/api/v1/photos/upload", response_model=PhotoUploadResponse, status_code=201)
async def upload_photo(
    camera_id: str = Form(..., description="相机ID"),
    file: UploadFile = File(..., description="图片文件"),
    captured_at: Optional[str] = Form(None, description="拍摄时间 ISO格式"),
    db: Session = Depends(get_db),
):
    content_type = file.content_type or "image/jpeg"
    if not is_valid_content_type(content_type):
        raise HTTPException(
            status_code=400,
            detail=f"不支持的文件类型: {content_type}. 支持的类型: jpeg, png, gif, webp, bmp",
        )

    image_bytes = await file.read()
    if len(image_bytes) == 0:
        raise HTTPException(status_code=400, detail="空文件")

    filename = file.filename or f"{camera_id}_{datetime.utcnow().strftime('%Y%m%d_%H%M%S')}.jpg"

    captured_at_dt = None
    if captured_at:
        try:
            captured_at_dt = datetime.fromisoformat(captured_at.replace("Z", "+00:00"))
        except ValueError:
            raise HTTPException(status_code=400, detail="captured_at 格式错误，请使用ISO格式")

    photo = save_photo_to_db(
        db=db,
        camera_id=camera_id,
        filename=filename,
        content_type=content_type,
        image_bytes=image_bytes,
        source_channel="http",
        captured_at=captured_at_dt,
    )
    return photo


@app.post("/api/v1/photos/upload-base64", response_model=PhotoUploadResponse, status_code=201)
async def upload_photo_base64(
    camera_id: str = Form(...),
    image_base64: str = Form(..., description="Base64编码的图片数据"),
    filename: Optional[str] = Form(None),
    content_type: Optional[str] = Form("image/jpeg"),
    captured_at: Optional[str] = Form(None),
    db: Session = Depends(get_db),
):
    try:
        image_bytes, detected_ct = parse_base64_image(image_base64)
        if detected_ct:
            content_type = detected_ct
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    if not is_valid_content_type(content_type):
        raise HTTPException(
            status_code=400,
            detail=f"不支持的文件类型: {content_type}",
        )

    if not filename:
        ext = content_type.split("/")[-1]
        filename = f"{camera_id}_{datetime.utcnow().strftime('%Y%m%d_%H%M%S')}.{ext}"

    captured_at_dt = None
    if captured_at:
        try:
            captured_at_dt = datetime.fromisoformat(captured_at.replace("Z", "+00:00"))
        except ValueError:
            raise HTTPException(status_code=400, detail="captured_at 格式错误")

    photo = save_photo_to_db(
        db=db,
        camera_id=camera_id,
        filename=filename,
        content_type=content_type,
        image_bytes=image_bytes,
        source_channel="http-base64",
        captured_at=captured_at_dt,
    )
    return photo


@app.get("/api/v1/photos", response_model=List[PhotoDetail])
async def list_photos(
    camera_id: Optional[str] = None,
    status: Optional[str] = None,
    category: Optional[str] = None,
    has_animal: Optional[bool] = None,
    min_confidence: Optional[float] = None,
    max_confidence: Optional[float] = None,
    start_time: Optional[datetime] = None,
    end_time: Optional[datetime] = None,
    skip: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=1000),
    db: Session = Depends(get_db),
):
    query = db.query(Photo)

    if camera_id:
        query = query.filter(Photo.camera_id == camera_id)
    if status:
        query = query.filter(Photo.status == status)
    if category:
        query = query.filter(Photo.category == category)
    if has_animal is not None:
        query = query.filter(Photo.has_animal == has_animal)
    if min_confidence is not None:
        query = query.filter(Photo.confidence >= min_confidence)
    if max_confidence is not None:
        query = query.filter(Photo.confidence <= max_confidence)
    if start_time:
        query = query.filter(Photo.created_at >= start_time)
    if end_time:
        query = query.filter(Photo.created_at <= end_time)

    photos = query.order_by(Photo.created_at.desc()).offset(skip).limit(limit).all()
    return photos


@app.get("/api/v1/photos/{photo_id}", response_model=PhotoDetail)
async def get_photo(photo_id: int, db: Session = Depends(get_db)):
    photo = db.query(Photo).filter(Photo.id == photo_id).first()
    if not photo:
        raise HTTPException(status_code=404, detail="照片不存在")
    return photo


@app.get("/api/v1/photos/{photo_id}/url")
async def get_photo_presigned_url(photo_id: int, db: Session = Depends(get_db)):
    photo = db.query(Photo).filter(Photo.id == photo_id).first()
    if not photo:
        raise HTTPException(status_code=404, detail="照片不存在")

    storage = get_minio_storage()
    url = storage.get_object_url(photo.minio_object_key)
    return {"photo_id": photo_id, "url": url, "expires_in": 3600}


@app.delete("/api/v1/photos/{photo_id}", status_code=204)
async def delete_photo(photo_id: int, db: Session = Depends(get_db)):
    photo = db.query(Photo).filter(Photo.id == photo_id).first()
    if not photo:
        raise HTTPException(status_code=404, detail="照片不存在")

    try:
        storage = get_minio_storage()
        storage.delete_object(photo.minio_object_key)
    except Exception as e:
        logger.warning(f"Failed to delete object from MinIO: {e}")

    db.delete(photo)
    db.commit()
    return None


@app.get("/api/v1/stats", response_model=StatsResponse)
async def get_stats(db: Session = Depends(get_db)):
    total = db.query(func.count(Photo.id)).scalar() or 0
    pending = db.query(func.count(Photo.id)).filter(Photo.status == PhotoStatus.PENDING.value).scalar() or 0
    empty = db.query(func.count(Photo.id)).filter(Photo.category == PhotoCategory.EMPTY.value).scalar() or 0
    animal = db.query(func.count(Photo.id)).filter(Photo.category == PhotoCategory.ANIMAL.value).scalar() or 0
    unknown = db.query(func.count(Photo.id)).filter(Photo.category == PhotoCategory.UNKNOWN.value).scalar() or 0
    failed = db.query(func.count(Photo.id)).filter(Photo.status == PhotoStatus.FAILED.value).scalar() or 0

    return StatsResponse(
        total_photos=total,
        pending_count=pending,
        empty_count=empty,
        animal_count=animal,
        unknown_count=unknown,
        failed_count=failed,
    )
