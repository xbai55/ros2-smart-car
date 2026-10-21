"""系统设置与运行配置：项目文档中的 /api/v1/system/*。"""
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from ...core.config import settings
from ...gateway import get_robot_gateway
from ...models import User
from ...schemas.ops import SettingUpdate
from ...services.realtime import get_realtime_store
from ...services.settings import mask_url, read_settings, update_settings
from ...services.storage import get_storage
from ...services.ws_manager import managers_status
from ..deps import get_db, require_permission

router = APIRouter(prefix="/system", tags=["system"])


@router.get("/info")
def system_info(
    db: Session = Depends(get_db),
    _: User = Depends(require_permission("settings.read")),
) -> dict:
    stored = read_settings(db, mask=False)
    gateway = get_robot_gateway(stored.get("robot_web_url") or stored.get("robot_gateway_url") or None)
    store = get_realtime_store()
    storage = get_storage()
    return {
        "name": stored.get("system_name") or settings.system_name,
        "version": settings.app_version,
        "database": settings.database_backend,
        "realtime": {"backend": store.backend, "available": store.is_available()},
        "storage": {"backend": storage.backend, "configured": storage.configured},
        "gateway": {"mode": gateway.mode, "target": mask_url(gateway.base_url) or None},
        "websocket": managers_status(),
    }


@router.get("/settings")
def get_system_settings(
    db: Session = Depends(get_db),
    _: User = Depends(require_permission("settings.read")),
) -> dict:
    return read_settings(db)


@router.put("/settings")
def put_system_settings(
    payload: SettingUpdate,
    db: Session = Depends(get_db),
    user: User = Depends(require_permission("settings.manage")),
) -> dict:
    return update_settings(db, payload.values, user)


@router.get("/config")
def get_system_config(
    db: Session = Depends(get_db),
    _: User = Depends(require_permission("settings.read")),
) -> dict:
    return read_settings(db)


@router.put("/config")
def put_system_config(
    payload: SettingUpdate,
    db: Session = Depends(get_db),
    user: User = Depends(require_permission("settings.manage")),
) -> dict:
    return update_settings(db, payload.values, user)
