import logging
from typing import List, Optional
from datetime import datetime

from fastapi import FastAPI, Depends, HTTPException, UploadFile, File, Form, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session
from sqlalchemy import func, and_, distinct

from common.config import settings
from common.database import get_db, init_db
from common.models import Photo, PhotoStatus, PhotoCategory, Detection, Group, PhotoGroup, GroupType
from common.schemas import (
    PhotoUploadResponse,
    PhotoDetail,
    PhotoQuery,
    StatsResponse,
    GroupCreate,
    GroupUpdate,
    GroupDetail,
    PhotoIdsRequest,
    GroupBatchAddResponse,
    GroupBatchRemoveResponse,
    GroupBrief,
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
    group_id: Optional[int] = Query(None, description="按组别ID筛选，只返回属于该组的照片"),
    exclude_group_id: Optional[int] = Query(None, description="排除组别ID，只返回不属于该组的照片"),
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
    if group_id is not None:
        query = query.filter(
            Photo.id.in_(
                db.query(PhotoGroup.photo_id).filter(PhotoGroup.group_id == group_id)
            )
        )
    if exclude_group_id is not None:
        subquery = db.query(PhotoGroup.photo_id).filter(PhotoGroup.group_id == exclude_group_id)
        query = query.filter(~Photo.id.in_(subquery))

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


VALID_GROUP_TYPES = {g.value for g in GroupType}


def _get_group_with_count(db: Session, group: Group) -> GroupDetail:
    count = (
        db.query(func.count(distinct(PhotoGroup.photo_id)))
        .filter(PhotoGroup.group_id == group.id)
        .scalar() or 0
    )
    return GroupDetail(
        id=group.id,
        name=group.name,
        group_type=group.group_type,
        description=group.description,
        color=group.color,
        cover_photo_id=group.cover_photo_id,
        sort_order=group.sort_order,
        created_at=group.created_at,
        updated_at=group.updated_at,
        photo_count=count,
    )


@app.post("/api/v1/groups", response_model=GroupDetail, status_code=201)
async def create_group(data: GroupCreate, db: Session = Depends(get_db)):
    if data.group_type not in VALID_GROUP_TYPES:
        raise HTTPException(
            status_code=400,
            detail=f"无效的 group_type: {data.group_type}，有效值: {sorted(VALID_GROUP_TYPES)}",
        )

    existing = db.query(Group).filter(Group.name == data.name.strip()).first()
    if existing:
        raise HTTPException(status_code=409, detail=f"组别名称已存在: {data.name}")

    if data.cover_photo_id is not None:
        cover = db.query(Photo).filter(Photo.id == data.cover_photo_id).first()
        if not cover:
            raise HTTPException(status_code=400, detail=f"封面照片不存在: id={data.cover_photo_id}")

    group = Group(
        name=data.name.strip(),
        group_type=data.group_type,
        description=data.description,
        color=data.color,
        cover_photo_id=data.cover_photo_id,
        sort_order=data.sort_order,
    )
    db.add(group)
    db.commit()
    db.refresh(group)
    logger.info(f"Created group id={group.id}, name={group.name}, type={group.group_type}")
    return _get_group_with_count(db, group)


@app.get("/api/v1/groups", response_model=List[GroupDetail])
async def list_groups(
    group_type: Optional[str] = Query(None, description="按类型筛选: area / tag / custom"),
    keyword: Optional[str] = Query(None, description="按名称模糊搜索"),
    db: Session = Depends(get_db),
):
    query = db.query(Group)
    if group_type:
        if group_type not in VALID_GROUP_TYPES:
            raise HTTPException(status_code=400, detail=f"无效的 group_type: {group_type}")
        query = query.filter(Group.group_type == group_type)
    if keyword:
        query = query.filter(Group.name.like(f"%{keyword}%"))
    groups = query.order_by(Group.sort_order.asc(), Group.created_at.asc()).all()
    return [_get_group_with_count(db, g) for g in groups]


@app.get("/api/v1/groups/{group_id}", response_model=GroupDetail)
async def get_group(group_id: int, db: Session = Depends(get_db)):
    group = db.query(Group).filter(Group.id == group_id).first()
    if not group:
        raise HTTPException(status_code=404, detail="组别不存在")
    return _get_group_with_count(db, group)


@app.put("/api/v1/groups/{group_id}", response_model=GroupDetail)
async def update_group(group_id: int, data: GroupUpdate, db: Session = Depends(get_db)):
    group = db.query(Group).filter(Group.id == group_id).first()
    if not group:
        raise HTTPException(status_code=404, detail="组别不存在")

    update_data = data.model_dump(exclude_unset=True)

    if "name" in update_data:
        new_name = update_data["name"].strip()
        existing = (
            db.query(Group)
            .filter(Group.name == new_name, Group.id != group_id)
            .first()
        )
        if existing:
            raise HTTPException(status_code=409, detail=f"组别名称已存在: {new_name}")
        group.name = new_name

    if "group_type" in update_data:
        if update_data["group_type"] not in VALID_GROUP_TYPES:
            raise HTTPException(status_code=400, detail=f"无效的 group_type: {update_data['group_type']}")
        group.group_type = update_data["group_type"]

    if "description" in update_data:
        group.description = update_data["description"]
    if "color" in update_data:
        group.color = update_data["color"]

    if "cover_photo_id" in update_data:
        if update_data["cover_photo_id"] is not None:
            cover = db.query(Photo).filter(Photo.id == update_data["cover_photo_id"]).first()
            if not cover:
                raise HTTPException(status_code=400, detail=f"封面照片不存在: id={update_data['cover_photo_id']}")
        group.cover_photo_id = update_data["cover_photo_id"]

    if "sort_order" in update_data:
        group.sort_order = update_data["sort_order"]

    group.updated_at = datetime.utcnow()
    db.commit()
    db.refresh(group)
    logger.info(f"Updated group id={group.id}, name={group.name}")
    return _get_group_with_count(db, group)


@app.delete("/api/v1/groups/{group_id}", status_code=204)
async def delete_group(group_id: int, db: Session = Depends(get_db)):
    group = db.query(Group).filter(Group.id == group_id).first()
    if not group:
        raise HTTPException(status_code=404, detail="组别不存在")
    db.delete(group)
    db.commit()
    logger.info(f"Deleted group id={group_id}, name={group.name}")
    return None


@app.post("/api/v1/groups/{group_id}/photos/batch-add", response_model=GroupBatchAddResponse)
async def batch_add_photos_to_group(
    group_id: int,
    data: PhotoIdsRequest,
    db: Session = Depends(get_db),
):
    group = db.query(Group).filter(Group.id == group_id).first()
    if not group:
        raise HTTPException(status_code=404, detail="组别不存在")

    existing_ids = set(
        row[0] for row in
        db.query(PhotoGroup.photo_id)
        .filter(PhotoGroup.group_id == group_id, PhotoGroup.photo_id.in_(data.photo_ids))
        .all()
    )

    valid_photos = {
        row[0]: True for row in
        db.query(Photo.id).filter(Photo.id.in_(data.photo_ids)).all()
    }

    added_ids: List[int] = []
    skipped_ids: List[int] = []

    now = datetime.utcnow()
    for pid in data.photo_ids:
        if pid in existing_ids:
            skipped_ids.append(pid)
            continue
        if pid not in valid_photos:
            skipped_ids.append(pid)
            continue
        db.add(PhotoGroup(photo_id=pid, group_id=group_id, added_at=now))
        added_ids.append(pid)

    group.updated_at = now
    db.commit()

    logger.info(
        f"Batch add to group id={group_id}: added={len(added_ids)}, skipped={len(skipped_ids)}, "
        f"total_requested={len(data.photo_ids)}"
    )

    return GroupBatchAddResponse(
        group_id=group_id,
        group_name=group.name,
        added_count=len(added_ids),
        skipped_count=len(skipped_ids),
        added_ids=added_ids,
        skipped_ids=skipped_ids,
    )


@app.post("/api/v1/groups/{group_id}/photos/batch-remove", response_model=GroupBatchRemoveResponse)
async def batch_remove_photos_from_group(
    group_id: int,
    data: PhotoIdsRequest,
    db: Session = Depends(get_db),
):
    group = db.query(Group).filter(Group.id == group_id).first()
    if not group:
        raise HTTPException(status_code=404, detail="组别不存在")

    removed = (
        db.query(PhotoGroup)
        .filter(PhotoGroup.group_id == group_id, PhotoGroup.photo_id.in_(data.photo_ids))
        .delete(synchronize_session=False)
    )
    group.updated_at = datetime.utcnow()
    db.commit()

    logger.info(
        f"Batch remove from group id={group_id}: removed={removed}, requested={len(data.photo_ids)}"
    )

    return GroupBatchRemoveResponse(
        group_id=group_id,
        group_name=group.name,
        removed_count=removed,
    )


@app.delete("/api/v1/groups/{group_id}/photos/clear", response_model=GroupBatchRemoveResponse)
async def clear_all_photos_from_group(group_id: int, db: Session = Depends(get_db)):
    group = db.query(Group).filter(Group.id == group_id).first()
    if not group:
        raise HTTPException(status_code=404, detail="组别不存在")

    removed = (
        db.query(PhotoGroup)
        .filter(PhotoGroup.group_id == group_id)
        .delete(synchronize_session=False)
    )
    group.updated_at = datetime.utcnow()
    db.commit()

    logger.info(f"Cleared all {removed} photos from group id={group_id}")

    return GroupBatchRemoveResponse(
        group_id=group_id,
        group_name=group.name,
        removed_count=removed,
    )


@app.get("/api/v1/groups/{group_id}/photos", response_model=List[PhotoDetail])
async def list_photos_in_group(
    group_id: int,
    camera_id: Optional[str] = None,
    category: Optional[str] = None,
    skip: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=1000),
    db: Session = Depends(get_db),
):
    group = db.query(Group).filter(Group.id == group_id).first()
    if not group:
        raise HTTPException(status_code=404, detail="组别不存在")

    query = (
        db.query(Photo)
        .join(PhotoGroup, PhotoGroup.photo_id == Photo.id)
        .filter(PhotoGroup.group_id == group_id)
    )
    if camera_id:
        query = query.filter(Photo.camera_id == camera_id)
    if category:
        query = query.filter(Photo.category == category)

    photos = query.order_by(PhotoGroup.added_at.desc()).offset(skip).limit(limit).all()
    return photos


@app.get("/api/v1/photos/{photo_id}/groups", response_model=List[GroupBrief])
async def get_groups_of_photo(photo_id: int, db: Session = Depends(get_db)):
    photo = db.query(Photo).filter(Photo.id == photo_id).first()
    if not photo:
        raise HTTPException(status_code=404, detail="照片不存在")

    groups = (
        db.query(Group)
        .join(PhotoGroup, PhotoGroup.group_id == Group.id)
        .filter(PhotoGroup.photo_id == photo_id)
        .order_by(Group.sort_order.asc(), Group.name.asc())
        .all()
    )
    return groups


@app.post("/api/v1/photos/{photo_id}/groups/{group_id}", status_code=201)
async def add_photo_to_single_group(
    photo_id: int,
    group_id: int,
    db: Session = Depends(get_db),
):
    photo = db.query(Photo).filter(Photo.id == photo_id).first()
    if not photo:
        raise HTTPException(status_code=404, detail="照片不存在")
    group = db.query(Group).filter(Group.id == group_id).first()
    if not group:
        raise HTTPException(status_code=404, detail="组别不存在")

    existing = (
        db.query(PhotoGroup)
        .filter(PhotoGroup.photo_id == photo_id, PhotoGroup.group_id == group_id)
        .first()
    )
    if existing:
        return {"photo_id": photo_id, "group_id": group_id, "status": "already_exists"}

    db.add(PhotoGroup(photo_id=photo_id, group_id=group_id))
    group.updated_at = datetime.utcnow()
    db.commit()
    return {"photo_id": photo_id, "group_id": group_id, "status": "added"}


@app.delete("/api/v1/photos/{photo_id}/groups/{group_id}", status_code=204)
async def remove_photo_from_single_group(
    photo_id: int,
    group_id: int,
    db: Session = Depends(get_db),
):
    photo = db.query(Photo).filter(Photo.id == photo_id).first()
    if not photo:
        raise HTTPException(status_code=404, detail="照片不存在")
    group = db.query(Group).filter(Group.id == group_id).first()
    if not group:
        raise HTTPException(status_code=404, detail="组别不存在")

    deleted = (
        db.query(PhotoGroup)
        .filter(PhotoGroup.photo_id == photo_id, PhotoGroup.group_id == group_id)
        .delete(synchronize_session=False)
    )
    if deleted:
        group.updated_at = datetime.utcnow()
        db.commit()
    return None
