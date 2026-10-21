"""媒体资源接口：预签名上传地址与本地文件回退。

对应项目文档中的 /api/v1/media/presign、/api/v1/media/complete，
存储实现见 services/storage.py（MinIO 优先，未配置时使用本地目录）。
"""
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from ...models import User
from ...services.ops import record_audit
from ...services.storage import get_storage, normalize_key
from ..deps import get_current_user, get_db

router = APIRouter(prefix="/media", tags=["media"])

_CONTENT_TYPES = {
    "png": "image/png",
    "jpg": "image/jpeg",
    "jpeg": "image/jpeg",
    "webp": "image/webp",
    "gif": "image/gif",
    "mp4": "video/mp4",
    "webm": "video/webm",
    "json": "application/json",
    "yaml": "text/yaml",
    "yml": "text/yaml",
    "pgm": "image/x-portable-graymap",
}


class PresignIn(BaseModel):
    key: str = Field(min_length=1, max_length=512)
    content_type: str = ""
    expires_in: int = Field(default=900, ge=60, le=86400)


class CompleteIn(BaseModel):
    key: str = Field(min_length=1, max_length=512)
    size: int = Field(default=0, ge=0)
    sha256: str = ""
    content_type: str = ""
    ref_type: Optional[str] = None
    ref_id: Optional[str] = None


def _bad_request(exc: ValueError) -> HTTPException:
    return HTTPException(status_code=400, detail={"code": "BAD_REQUEST", "message": str(exc)})


@router.post("/presign")
def presign(payload: PresignIn, _: User = Depends(get_current_user)) -> dict:
    try:
        return get_storage().presign_upload(payload.key, expires_in=payload.expires_in)
    except ValueError as exc:
        raise _bad_request(exc)


@router.post("/complete")
def complete(
    payload: CompleteIn,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict:
    storage = get_storage()
    try:
        key = normalize_key(payload.key)
    except ValueError as exc:
        raise _bad_request(exc)
    record_audit(
        db,
        user,
        "media.complete",
        "media",
        None,
        after={
            "key": key,
            "size": payload.size,
            "sha256": payload.sha256,
            "ref_type": payload.ref_type,
            "ref_id": payload.ref_id,
        },
    )
    db.commit()
    return {
        "key": key,
        "size": payload.size,
        "sha256": payload.sha256,
        "content_type": payload.content_type,
        "backend": storage.backend,
        "ref_type": payload.ref_type,
        "ref_id": payload.ref_id,
    }


async def _store_object(key: str, request: Request) -> dict:
    data = await request.body()
    try:
        return get_storage().put(key, data, content_type=request.headers.get("content-type", ""))
    except ValueError as exc:
        raise _bad_request(exc)


@router.put("/object/{key:path}")
async def upload_object_put(
    key: str,
    request: Request,
    _: User = Depends(get_current_user),
) -> dict:
    return await _store_object(key, request)


@router.post("/object/{key:path}")
async def upload_object_post(
    key: str,
    request: Request,
    _: User = Depends(get_current_user),
) -> dict:
    return await _store_object(key, request)


@router.get("/object/{key:path}")
def get_object(key: str, _: User = Depends(get_current_user)) -> Response:
    try:
        data = get_storage().get(key)
    except ValueError as exc:
        raise _bad_request(exc)
    if data is None:
        raise HTTPException(status_code=404, detail={"code": "NOT_FOUND", "message": "资源不存在"})
    suffix = key.rsplit(".", 1)[-1].lower() if "." in key else ""
    return Response(content=data, media_type=_CONTENT_TYPES.get(suffix, "application/octet-stream"))
