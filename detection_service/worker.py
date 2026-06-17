import json
import logging
import threading
import time
import random
from pathlib import Path
from typing import List, Optional
from datetime import datetime, timedelta

from sqlalchemy.orm import Session
from sqlalchemy.exc import OperationalError

from common.config import settings
from common.database import SessionLocal
from common.models import Photo, PhotoStatus, PhotoCategory, Detection
from detection_service.detector import get_detector

logger = logging.getLogger(__name__)

DEADLOCK_ERROR_CODES = {1205, 1213}
STUCK_DETECTING_THRESHOLD_MINUTES = 10
MAX_RETRIES = 3


def _is_deadlock_error(exc: OperationalError) -> bool:
    orig = getattr(exc, "orig", None)
    if orig is None:
        return False
    errno = getattr(orig, "errno", None)
    if errno in DEADLOCK_ERROR_CODES:
        return True
    msg = str(exc).lower()
    return "deadlock" in msg or "lock wait timeout" in msg


class DetectionWorker:
    def __init__(self):
        self._running = False
        self._thread: Optional[threading.Thread] = None
        self._detector = None
        self._poll_interval = settings.DETECTION_POLL_INTERVAL
        self._batch_size = settings.DETECTION_BATCH_SIZE
        self._empty_threshold = settings.EMPTY_PHOTO_THRESHOLD
        self._last_stuck_recovery = datetime.utcnow()

    def _init(self):
        if self._detector is None:
            self._detector = get_detector()
            self._detector._ensure_loaded()

    def _fetch_single_pending_photo(self, db: Session) -> Optional[Photo]:
        for attempt in range(MAX_RETRIES):
            try:
                photo = (
                    db.query(Photo)
                    .filter(Photo.status == PhotoStatus.PENDING.value)
                    .order_by(Photo.created_at.asc())
                    .with_for_update(skip_locked=True)
                    .limit(1)
                    .first()
                )
                if photo:
                    photo.status = PhotoStatus.DETECTING.value
                    photo.updated_at = datetime.utcnow()
                    db.commit()
                    db.refresh(photo)
                return photo
            except OperationalError as e:
                db.rollback()
                if _is_deadlock_error(e) and attempt < MAX_RETRIES - 1:
                    wait = (2 ** attempt) * 0.1 + random.uniform(0, 0.1)
                    logger.warning(
                        f"Deadlock fetching pending photo (attempt {attempt+1}/{MAX_RETRIES}), "
                        f"retrying in {wait:.2f}s"
                    )
                    time.sleep(wait)
                    continue
                logger.error(f"Failed to fetch pending photo after {MAX_RETRIES} attempts: {e}")
                raise

    def _recover_stuck_detecting_photos(self, db: Session) -> int:
        threshold = datetime.utcnow() - timedelta(minutes=STUCK_DETECTING_THRESHOLD_MINUTES)
        try:
            count = (
                db.query(Photo)
                .filter(
                    Photo.status == PhotoStatus.DETECTING.value,
                    Photo.updated_at < threshold,
                )
                .update(
                    {Photo.status: PhotoStatus.PENDING.value, Photo.updated_at: datetime.utcnow()},
                    synchronize_session=False,
                )
            )
            db.commit()
            if count > 0:
                logger.info(f"Recovered {count} photos stuck in 'detecting' status")
            return count
        except OperationalError as e:
            db.rollback()
            if _is_deadlock_error(e):
                logger.warning(f"Deadlock during stuck recovery, skipping this round: {e}")
                return 0
            raise

    def _update_photo_with_retry(
        self,
        db: Session,
        photo_id: int,
        updates: dict,
        detections: Optional[List[dict]] = None,
    ) -> None:
        for attempt in range(MAX_RETRIES):
            try:
                photo = db.query(Photo).filter(Photo.id == photo_id).first()
                if not photo:
                    logger.warning(f"Photo id={photo_id} not found during update")
                    return

                for key, value in updates.items():
                    setattr(photo, key, value)

                if detections:
                    for det in detections:
                        detection_record = Detection(
                            photo_id=photo_id,
                            class_name=det["class_name"],
                            confidence=det["confidence"],
                            bbox_x1=det["bbox_x1"],
                            bbox_y1=det["bbox_y1"],
                            bbox_x2=det["bbox_x2"],
                            bbox_y2=det["bbox_y2"],
                            model_name=Path(settings.YOLO_MODEL_PATH).name,
                        )
                        db.add(detection_record)

                db.commit()
                return
            except OperationalError as e:
                db.rollback()
                if _is_deadlock_error(e) and attempt < MAX_RETRIES - 1:
                    wait = (2 ** attempt) * 0.1 + random.uniform(0, 0.1)
                    logger.warning(
                        f"Deadlock updating photo id={photo_id} (attempt {attempt+1}/{MAX_RETRIES}), "
                        f"retrying in {wait:.2f}s"
                    )
                    time.sleep(wait)
                    continue
                raise

    def _process_photo(self, photo_id: int) -> bool:
        db = SessionLocal()
        try:
            photo = db.query(Photo).filter(Photo.id == photo_id).first()
            if not photo:
                logger.warning(f"Photo id={photo_id} not found")
                return False

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

            updates = {
                "status": PhotoStatus.COMPLETED.value,
                "category": category,
                "has_animal": has_animal,
                "confidence": max_confidence,
                "detected_classes": json.dumps(result["detected_classes"], ensure_ascii=False),
                "updated_at": datetime.utcnow(),
            }

            self._update_photo_with_retry(
                db=db,
                photo_id=photo_id,
                updates=updates,
                detections=result["detections"],
            )

            logger.info(
                f"Processed photo id={photo_id}: category={category}, "
                f"has_animal={has_animal}, confidence={max_confidence:.4f}, "
                f"detections={result['total_detections']}"
            )
            return True

        except Exception as e:
            logger.exception(f"Failed to process photo id={photo_id}: {e}")
            try:
                self._update_photo_with_retry(
                    db=db,
                    photo_id=photo_id,
                    updates={
                        "status": PhotoStatus.FAILED.value,
                        "updated_at": datetime.utcnow(),
                    },
                )
            except Exception as update_err:
                logger.error(f"Failed to mark photo id={photo_id} as failed: {update_err}")
            return False
        finally:
            db.close()

    def _run_loop(self):
        logger.info(
            f"Detection worker started. "
            f"poll_interval={self._poll_interval}s, batch_size={self._batch_size}, "
            f"empty_threshold={self._empty_threshold}"
        )
        empty_count = 0

        while self._running:
            try:
                now = datetime.utcnow()
                if (now - self._last_stuck_recovery) > timedelta(minutes=5):
                    db = SessionLocal()
                    try:
                        self._recover_stuck_detecting_photos(db)
                    finally:
                        db.close()
                    self._last_stuck_recovery = now

                db = SessionLocal()
                try:
                    photo = self._fetch_single_pending_photo(db)
                finally:
                    db.close()

                if not photo:
                    empty_count += 1
                    sleep_time = min(self._poll_interval, 1 + empty_count * 0.5)
                    time.sleep(sleep_time)
                    continue

                empty_count = 0
                self._process_photo(photo.id)

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
            for attempt in range(MAX_RETRIES):
                try:
                    photo = (
                        db.query(Photo)
                        .filter(Photo.id == photo_id)
                        .with_for_update(skip_locked=True)
                        .first()
                    )
                    if not photo:
                        raise ValueError(f"Photo id={photo_id} not found or locked by another process")

                    photo.status = PhotoStatus.DETECTING.value
                    photo.updated_at = datetime.utcnow()
                    db.commit()
                    break
                except OperationalError as e:
                    db.rollback()
                    if _is_deadlock_error(e) and attempt < MAX_RETRIES - 1:
                        wait = (2 ** attempt) * 0.1 + random.uniform(0, 0.1)
                        logger.warning(
                            f"Deadlock locking photo id={photo_id} (attempt {attempt+1}/{MAX_RETRIES}), "
                            f"retrying in {wait:.2f}s"
                        )
                        time.sleep(wait)
                        continue
                    raise
        finally:
            db.close()

        success = self._process_photo(photo_id)

        db = SessionLocal()
        try:
            photo = db.query(Photo).filter(Photo.id == photo_id).first()
            return {
                "photo_id": photo_id,
                "success": success,
                "status": photo.status if photo else None,
                "category": photo.category if photo else None,
                "has_animal": photo.has_animal if photo else None,
                "confidence": photo.confidence if photo else None,
            }
        finally:
            db.close()


detection_worker = DetectionWorker()
