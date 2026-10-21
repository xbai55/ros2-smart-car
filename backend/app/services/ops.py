import json
from datetime import datetime, timezone
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import AuditLog, Notification, User


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def iso(value: datetime | None) -> str | None:
    return value.isoformat() if value else None


def json_loads(value: str | None, default=None):
    if not value:
        return default if default is not None else []
    try:
        return json.loads(value)
    except Exception:
        return default if default is not None else []


def record_audit(
    db: Session,
    user: User,
    action: str,
    resource: str,
    resource_id: str | None = None,
    *,
    before: dict | None = None,
    after: dict | None = None,
    request_id: str | None = None,
) -> None:
    db.add(
        AuditLog(
            id=str(uuid4()),
            user_id=user.id if user else None,
            action=action,
            resource=resource,
            resource_id=resource_id,
            request_id=request_id,
            before=json.dumps(before or {}, ensure_ascii=False),
            after=json.dumps(after or {}, ensure_ascii=False),
        )
    )


def notify_users(
    db: Session,
    *,
    kind: str,
    title: str,
    body: str,
    ref_id: str | None = None,
    users: list[User] | None = None,
) -> None:
    targets = users if users is not None else db.execute(select(User)).scalars().all()
    for target in targets:
        db.add(
            Notification(
                id=str(uuid4()),
                user_id=target.id,
                kind=kind,
                title=title,
                body=body,
                ref_id=ref_id,
            )
        )


def serialize_audit(log: AuditLog) -> dict:
    return {
        "id": log.id,
        "user_id": log.user_id,
        "action": log.action,
        "resource": log.resource,
        "resource_id": log.resource_id,
        "request_id": log.request_id,
        "before": json_loads(log.before, {}),
        "after": json_loads(log.after, {}),
        "created_at": iso(log.created_at),
    }


def serialize_notification(notification: Notification) -> dict:
    return {
        "id": notification.id,
        "user_id": notification.user_id,
        "kind": notification.kind,
        "title": notification.title,
        "body": notification.body,
        "ref_id": notification.ref_id,
        "read": notification.read,
        "created_at": iso(notification.created_at),
    }
