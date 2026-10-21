from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from ...models import User
from ...schemas.ops import SettingUpdate
from ...services.settings import read_settings, update_settings
from ..deps import get_db, require_permission

router = APIRouter(prefix="/settings", tags=["settings"])


@router.get("")
def get_settings(
    db: Session = Depends(get_db),
    _: User = Depends(require_permission("settings.read")),
) -> dict:
    return read_settings(db)


@router.put("")
def put_settings(
    payload: SettingUpdate,
    db: Session = Depends(get_db),
    user: User = Depends(require_permission("settings.manage")),
) -> dict:
    return update_settings(db, payload.values, user)
