from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from ...core.pagination import run_list
from ...models import AuditLog, User
from ...services.ops import serialize_audit
from ..deps import get_db, require_permission

router = APIRouter(prefix="/audit-logs", tags=["audit"])


@router.get("")
def list_audit_logs(
    db: Session = Depends(get_db),
    _: User = Depends(require_permission("audit.read")),
    action: str | None = Query(default=None),
    resource: str | None = Query(default=None),
    user_id: str | None = Query(default=None),
    page: int | None = Query(default=None, ge=1),
    page_size: int | None = Query(default=None, ge=1, le=200),
):
    stmt = select(AuditLog).order_by(AuditLog.created_at.desc())
    if action:
        stmt = stmt.where(AuditLog.action == action)
    if resource:
        stmt = stmt.where(AuditLog.resource == resource)
    if user_id:
        stmt = stmt.where(AuditLog.user_id == user_id)
    if page is None and page_size is None:
        # 兼容既有调用：默认只返回最近 200 条
        stmt = stmt.limit(200)
    return run_list(db, stmt, serialize_audit, page, page_size)
