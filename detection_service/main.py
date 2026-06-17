import logging
from typing import Optional, List
from datetime import datetime

from fastapi import FastAPI, Depends, HTTPException, Query, BackgroundTasks
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.orm import Session
from sqlalchemy import func

from common.config import settings
from common.database import get_db, init_db
from common.models import Photo, PhotoStatus, PhotoCategory, Detection
from common.schemas import PhotoDetail, StatsResponse
from detection_service.worker import detection_worker
from detection_service.detector import get_detector

logging.basicConfig(
    level=getattr(logging, settings.DETECTION_LOG_LEVEL, logging.INFO),
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)

app = FastAPI(
    title="Photo Detection Service",
    description="空拍照片检测服务 - YOLOv8轻量模型",
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
    try:
        detection_worker.start()
    except Exception as e:
        logger.error(f"Failed to start detection worker: {e}")
        raise


@app.on_event("shutdown")
async def shutdown_event():
    detection_worker.stop()
    logger.info("Detection worker stopped")


@app.get("/health")
async def health_check():
    detector = get_detector()
    model_loaded = detector._model_loaded
    return {
        "status": "healthy",
        "service": "detection",
        "model_loaded": model_loaded,
        "model_path": settings.YOLO_MODEL_PATH,
        "animal_classes": settings.animal_class_list,
        "empty_threshold": settings.EMPTY_PHOTO_THRESHOLD,
        "timestamp": datetime.utcnow().isoformat(),
    }


@app.get("/api/v1/detect/queue")
async def get_queue_status(db: Session = Depends(get_db)):
    pending = db.query(func.count(Photo.id)).filter(Photo.status == PhotoStatus.PENDING.value).scalar() or 0
    detecting = db.query(func.count(Photo.id)).filter(Photo.status == PhotoStatus.DETECTING.value).scalar() or 0
    completed = db.query(func.count(Photo.id)).filter(Photo.status == PhotoStatus.COMPLETED.value).scalar() or 0
    failed = db.query(func.count(Photo.id)).filter(Photo.status == PhotoStatus.FAILED.value).scalar() or 0

    return {
        "pending": pending,
        "detecting": detecting,
        "completed": completed,
        "failed": failed,
        "worker_running": detection_worker._running,
    }


@app.post("/api/v1/detect/photo/{photo_id}")
async def detect_single_photo(photo_id: int, background_tasks: BackgroundTasks):
    background_tasks.add_task(detection_worker.process_single_photo, photo_id)
    return {
        "message": f"Detection task submitted for photo id={photo_id}",
        "photo_id": photo_id,
    }


@app.post("/api/v1/detect/photo/{photo_id}/sync")
async def detect_single_photo_sync(photo_id: int):
    try:
        result = detection_worker.process_single_photo(photo_id)
        return result
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/v1/detect/retry-failed")
async def retry_failed_photos(db: Session = Depends(get_db)):
    failed_count = (
        db.query(Photo)
        .filter(Photo.status == PhotoStatus.FAILED.value)
        .update({Photo.status: PhotoStatus.PENDING.value}, synchronize_session=False)
    )
    db.commit()
    return {
        "message": f"Reset {failed_count} failed photos to pending status",
        "reset_count": failed_count,
    }


@app.post("/api/v1/detect/reset-all")
async def reset_all_photos(
    confirm: bool = Query(False, description="必须设置为 true 才能执行重置"),
    db: Session = Depends(get_db),
):
    if not confirm:
        raise HTTPException(status_code=400, detail="请设置 confirm=true 确认执行重置操作")

    db.query(Detection).delete()

    reset_count = (
        db.query(Photo)
        .filter(Photo.status.in_([PhotoStatus.COMPLETED.value, PhotoStatus.FAILED.value, PhotoStatus.DETECTING.value]))
        .update(
            {
                Photo.status: PhotoStatus.PENDING.value,
                Photo.category: PhotoCategory.UNKNOWN.value,
                Photo.has_animal: None,
                Photo.confidence: None,
                Photo.detected_classes: None,
            },
            synchronize_session=False,
        )
    )
    db.commit()
    return {
        "message": f"Reset {reset_count} photos and cleared detection records",
        "reset_count": reset_count,
    }


@app.get("/api/v1/photos/empty", response_model=List[PhotoDetail])
async def list_empty_photos(
    camera_id: Optional[str] = None,
    min_confidence: Optional[float] = None,
    max_confidence: Optional[float] = None,
    skip: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=1000),
    db: Session = Depends(get_db),
):
    query = db.query(Photo).filter(Photo.category == PhotoCategory.EMPTY.value)
    if camera_id:
        query = query.filter(Photo.camera_id == camera_id)
    if min_confidence is not None:
        query = query.filter(Photo.confidence >= min_confidence)
    if max_confidence is not None:
        query = query.filter(Photo.confidence <= max_confidence)
    return query.order_by(Photo.created_at.desc()).offset(skip).limit(limit).all()


@app.get("/api/v1/photos/animal", response_model=List[PhotoDetail])
async def list_animal_photos(
    camera_id: Optional[str] = None,
    min_confidence: Optional[float] = None,
    max_confidence: Optional[float] = None,
    skip: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=1000),
    db: Session = Depends(get_db),
):
    query = db.query(Photo).filter(Photo.category == PhotoCategory.ANIMAL.value)
    if camera_id:
        query = query.filter(Photo.camera_id == camera_id)
    if min_confidence is not None:
        query = query.filter(Photo.confidence >= min_confidence)
    if max_confidence is not None:
        query = query.filter(Photo.confidence <= max_confidence)
    return query.order_by(Photo.created_at.desc()).offset(skip).limit(limit).all()


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


@app.get("/api/v1/stats/detailed")
async def get_detailed_stats(db: Session = Depends(get_db)):
    total = db.query(func.count(Photo.id)).scalar() or 0

    category_stats = (
        db.query(Photo.category, func.count(Photo.id))
        .group_by(Photo.category)
        .all()
    )
    category_counts = {cat: cnt for cat, cnt in category_stats}

    camera_stats = (
        db.query(Photo.camera_id, Photo.category, func.count(Photo.id))
        .group_by(Photo.camera_id, Photo.category)
        .all()
    )

    class_stats = (
        db.query(Detection.class_name, func.count(Detection.id))
        .filter(Detection.confidence >= settings.CONFIDENCE_THRESHOLD)
        .group_by(Detection.class_name)
        .order_by(func.count(Detection.id).desc())
        .limit(20)
        .all()
    )

    avg_confidence = (
        db.query(func.avg(Photo.confidence))
        .filter(Photo.confidence.isnot(None))
        .scalar()
    )

    return {
        "total_photos": total,
        "category_breakdown": {
            "empty": category_counts.get(PhotoCategory.EMPTY.value, 0),
            "animal": category_counts.get(PhotoCategory.ANIMAL.value, 0),
            "unknown": category_counts.get(PhotoCategory.UNKNOWN.value, 0),
        },
        "camera_breakdown": [
            {"camera_id": cid, "category": cat, "count": cnt}
            for cid, cat, cnt in camera_stats
        ],
        "top_detected_classes": [
            {"class_name": cls, "count": cnt}
            for cls, cnt in class_stats
        ],
        "average_confidence": float(avg_confidence) if avg_confidence else 0.0,
        "threshold_settings": {
            "confidence_threshold": settings.CONFIDENCE_THRESHOLD,
            "empty_photo_threshold": settings.EMPTY_PHOTO_THRESHOLD,
            "animal_classes": settings.animal_class_list,
        },
    }
