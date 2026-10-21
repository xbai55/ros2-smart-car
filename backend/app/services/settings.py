"""系统设置（app_settings 键值表）读写，/settings 与 /system/* 共用。"""
from __future__ import annotations

import re
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..core.config import settings
from ..models import AppSetting
from ..models.user import User
from .ops import record_audit

SENSITIVE_HINTS = ("secret", "password", "token", "api_key", "access_key")

DEFAULT_SETTINGS: dict[str, str] = {
    "system_name": settings.system_name,
    "robot_gateway_url": settings.robot_gateway_url,
    "robot_web_url": settings.robot_web_url,
    "video_service_url": settings.video_service_url,
    "heartbeat_timeout_seconds": "30",
    "task_retry_limit": "3",
    "map_default_resolution": "0.05",
    "log_retention_days": "30",
}


def is_sensitive(key: str) -> bool:
    return any(hint in key.lower() for hint in SENSITIVE_HINTS)


def mask_url(url: str | None) -> str | None:
    if not url:
        return url
    return re.sub(r"//[^/@]+@", "//***@", url)


def read_settings(db: Session, *, mask: bool = True) -> dict:
    stored = {item.key: item.value for item in db.execute(select(AppSetting)).scalars().all()}
    merged = {**DEFAULT_SETTINGS, **stored}
    if not mask:
        return merged
    return {key: ("***" if is_sensitive(key) and value else value) for key, value in merged.items()}


def update_settings(db: Session, values: dict[str, str], actor: User | None) -> dict:
    existing = {item.key: item for item in db.execute(select(AppSetting)).scalars().all()}
    before = {key: item.value for key, item in existing.items()}
    for key, value in values.items():
        item = existing.get(key)
        if item is None:
            db.add(AppSetting(id=str(uuid4()), key=key, value=value))
        else:
            item.value = value
    record_audit(db, actor, "settings.update", "settings", before=before, after=values)
    db.commit()
    return read_settings(db)
