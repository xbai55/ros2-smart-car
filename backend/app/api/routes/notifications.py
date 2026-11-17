from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select, update
from sqlalchemy.orm import Session

from ...core.pagination import run_list
from ...models import Notification, User
from ...schemas.ops import NotificationRead
from ...services.ops import serialize_notification
from ..deps import get_current_user, get_db, require_permission

router = APIRouter(prefix="/notifications", tags=["notifications"])


@router.get("")
def list_notifications(
    db: Session = Depends(get_db),
    user: User = Depends(require_permission("notifications.read")),
    unread: bool | None = Query(default=None, description="true 时只返回未读通知"),
    kind: str | None = Query(default=None),
    page: int | None = Query(default=None, ge=1),
    page_size: int | None = Query(default=None, ge=1, le=200),
):
    stmt = (
        select(Notification)
        .where(Notification.user_id == user.id)
        .order_by(Notification.created_at.desc())
    )
    if unread:
        stmt = stmt.where(Notification.read.is_(False))
    if kind:
        stmt = stmt.where(Notification.kind == kind)
    return run_list(db, stmt, serialize_notification, page, page_size)


@router.post('/read-all')
def mark_all_read(db: Session = Depends(get_db), user: User = Depends(require_permission('notifications.read'))):
    # One atomic update: notifications arriving afterwards remain unread.
    ids=list(db.scalars(update(Notification).where(Notification.user_id==user.id, Notification.read.is_(False))
                        .values(read=True).returning(Notification.id)))
    db.commit()
    return {'updated_count':len(ids), 'read_ids':ids}


@router.post("/{notification_id}/read")
def mark_read(
    notification_id: str,
    payload: NotificationRead,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict:
    item = db.get(Notification, notification_id)
    if item is None or item.user_id != user.id:
        raise HTTPException(status_code=404, detail={"code": "NOT_FOUND", "message": "通知不存在"})
    item.read = payload.read
    db.commit()
    return serialize_notification(item)
