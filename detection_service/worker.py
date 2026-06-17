import json
import logging
import threading
import time
from typing import List, Optional
from datetime import datetime

from sqlalchemy.orm import Session

from common.config import settings
from common.database import SessionLocal
from common.models import Photo, PhotoStatus, PhotoCategory, Detection
from detection_service.detector import get_detector

logger = logging.getLogger(__name__)


class DetectionWorker:
    def __init__(self):
        self._running = False
        self._thread: Optional[threading.Thread] = None
        self._detector = None
        self._poll_interval = settings.DETECTION_POLL_INTERVAL
        self._batch_size = settings.DETECTION_BATCH_SIZE
        self._empty_threshold = settings.EMPTY_PHOTO_THRESHOLD

    def _init(self):
        if self._detector is None:
            self._detector = get_detector()
            self._detector._ensure_loaded()

    def _fetch_pending_photos(self, db: Session) -> List[Photo]:
        photos = (
            db.query(Photo)
            .filter(Photo.status == PhotoStatus.PENDING.value)
            .order_by(Photo.created_at.asc())
            .limit(self._batch_size)
            .all()
        )
        if photos:
            photo_ids = [p.id for p in photos]
            db.query(Photo).filter(Photo.id.in_(photo_ids)).update(
                {Photo.status: PhotoStatus.DETECTING.value},
                synchronize_session=False,
            )
            db.commit()
        return photos

    def _process_photo(self, db: Session, photo: Photo) -> bool:
        try:
            from ingestion_service.storage import get_minio_storage
            storage = get_minio_storage()
            image_bytes = storage.get_object_bytes(photo.minio_object_key)

            result = self._detector.detect(image_bytes)

            has_animal = result["has_animal"]
            max_confidence = result["max_confidence"]

            if has_animal and max_confidence >= self._empty_threshold:
                category = PhotoCategory.ANIMAL.value
            else:
                category = PhotoCategory.EMPTY.value

            photo.status = PhotoStatus.COMPLETED.value
            photo.category = category
            photo.has_animal = has_animal
            photo.confidence = max_confidence
            photo.detected_classes = json.dumps(result["detected_classes"], ensure_ascii=False)
            photo.updated_at = datetime.utcnow()

            for det in result["detections"]:
                detection_record = Detection(
                    photo_id=photo.id,
                    class_name=det["class_name"],
                    confidence=det["confidence"],
                    bbox_x1=det["bbox_x1"],
                    bbox_y1=det["bbox_y1"],
                    bbox_x2=det["bbox_x2"],
                    bbox_y2=det["bbox_y2"],
                    model_name=Path(settings.YOLO_MODEL_PATH).name,
                )
                db.add(detection_record)

            logger.info(
                f"Processed photo id={photo.id}: category={category}, "
                f"has_animal={has_animal}, confidence={max_confidence:.4f}, "
                f"detections={result['total_detections']}"
            )
            return True

        except Exception as e:
            logger.exception(f"Failed to process photo id={photo.id}: {e}")
            photo.status = PhotoStatus.FAILED.value
            photo.updated_at = datetime.utcnow()
            return False

    def _run_loop(self):
        logger.info(
            f"Detection worker started. "
            f"poll_interval={self._poll_interval}s, batch_size={self._batch_size}, "
            f"empty_threshold={self._empty_threshold}"
        )
        while self._running:
            try:
                db = SessionLocal()
                try:
                    photos = self._fetch_pending_photos(db)
                    if not photos:
                        time.sleep(self._poll_interval)
                        continue

                    logger.info(f"Processing batch of {len(photos)} photos...")
                    for photo in photos:
                        if not self._running:
                            break
                        try:
                            self._process_photo(db, photo)
                            db.commit()
                        except Exception as e:
                            logger.exception(f"Error processing photo id={photo.id}: {e}")
                            db.rollback()
                            photo.status = PhotoStatus.FAILED.value
                            photo.updated_at = datetime.utcnow()
                            db.commit()

                finally:
                    db.close()

            except Exception as e:
                logger.exception(f"Worker loop error: {e}")
                time.sleep(self._poll_interval)

        logger.info("Detection worker stopped")

    def start(self):
        if self._running:
            return
        self._init()
        self._running = True
        self._thread = threading.Thread(target=self._run_loop, name="detection-worker", daemon=True)
        self._thread.start()
        logger.info("Detection worker thread started")

    def stop(self):
        self._running = False
        if self._thread:
            self._thread.join(timeout=30)
        logger.info("Detection worker stopped")

    def process_single_photo(self, photo_id: int) -> dict:
        self._init()
        db = SessionLocal()
        try:
            photo = db.query(Photo).filter(Photo.id == photo_id).first()
            if not photo:
                raise ValueError(f"Photo id={photo_id} not found")

            photo.status = PhotoStatus.DETECTING.value
            db.commit()

            success = self._process_photo(db, photo)
            db.commit()

            return {
                "photo_id": photo_id,
                "success": success,
                "status": photo.status,
                "category": photo.category,
                "has_animal": photo.has_animal,
                "confidence": photo.confidence,
            }
        except Exception as e:
            logger.exception(f"Manual processing failed for photo id={photo_id}: {e}")
            db.rollback()
            raise
        finally:
            db.close()


from pathlib import Path

detection_worker = DetectionWorker()
