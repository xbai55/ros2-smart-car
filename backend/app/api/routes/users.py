from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from ...core.pagination import run_list
from ...core.security import hash_password
from ...models.user import Role, User
from ...schemas.user import RoleCreate, UserCreate, UserUpdate
from ...services.ops import record_audit
from ...services.rbac import (
    create_role,
    list_permissions,
    list_roles,
    serialize_role,
    serialize_user,
)
from ..deps import get_db, require_permission

router = APIRouter(prefix="/users", tags=["users"])


@router.get("")
def list_users(
    db: Session = Depends(get_db),
    _: User = Depends(require_permission("users.manage")),
    keyword: str | None = Query(default=None),
    active: bool | None = Query(default=None),
    page: int | None = Query(default=None, ge=1),
    page_size: int | None = Query(default=None, ge=1, le=200),
):
    stmt = select(User).order_by(User.username)
    if keyword:
        like = f"%{keyword}%"
        stmt = stmt.where(or_(User.username.like(like), User.display_name.like(like)))
    if active is not None:
        stmt = stmt.where(User.active.is_(active))
    return run_list(db, stmt, serialize_user, page, page_size)


@router.post("", status_code=201)
def create_user(
    payload: UserCreate,
    db: Session = Depends(get_db),
    actor: User = Depends(require_permission("users.manage")),
) -> dict:
    exists = db.execute(select(User).where(User.username == payload.username)).scalar_one_or_none()
    if exists:
        raise HTTPException(status_code=409, detail={"code": "CONFLICT", "message": "用户名已存在"})
    user = User(
        id=str(uuid4()),
        username=payload.username,
        password_hash=hash_password(payload.password),
        display_name=payload.display_name,
        email=payload.email,
        active=payload.active,
    )
    user.roles = _resolve_roles(db, payload.role_names)
    db.add(user)
    db.flush()
    record_audit(db, actor, "users.create", "user", user.id, after={"username": user.username})
    db.commit()
    return serialize_user(user)


def _resolve_roles(db: Session, names: list[str] | None) -> list[Role]:
    unique = set(names or [])
    if not unique:
        return []
    roles = db.execute(select(Role).where(Role.name.in_(unique))).scalars().all()
    if len(roles) != len(unique):
        missing = unique - {r.name for r in roles}
        raise HTTPException(
            status_code=400,
            detail={"code": "BAD_REQUEST", "message": f"角色不存在：{', '.join(sorted(missing))}"},
        )
    return list(roles)


@router.get("/roles")
def list_user_roles(
    db: Session = Depends(get_db),
    _: User = Depends(require_permission("users.manage")),
) -> list[dict]:
    return list_roles(db)


@router.post("/roles", status_code=201)
def create_user_role(
    payload: RoleCreate,
    db: Session = Depends(get_db),
    actor: User = Depends(require_permission("users.manage")),
) -> dict:
    return serialize_role(create_role(db, payload, actor))


@router.get("/permissions")
def list_user_permissions(
    db: Session = Depends(get_db),
    _: User = Depends(require_permission("users.manage")),
) -> list[dict]:
    return list_permissions(db)


@router.get("/{user_id}")
def get_user(
    user_id: str,
    db: Session = Depends(get_db),
    _: User = Depends(require_permission("users.manage")),
) -> dict:
    user = db.get(User, user_id)
    if user is None:
        raise HTTPException(status_code=404, detail={"code": "NOT_FOUND", "message": "用户不存在"})
    return serialize_user(user)


@router.put("/{user_id}")
def update_user(
    user_id: str,
    payload: UserUpdate,
    db: Session = Depends(get_db),
    actor: User = Depends(require_permission("users.manage")),
) -> dict:
    user = db.get(User, user_id)
    if user is None:
        raise HTTPException(status_code=404, detail={"code": "NOT_FOUND", "message": "用户不存在"})
    if payload.display_name is not None:
        user.display_name = payload.display_name
    if payload.email is not None:
        user.email = payload.email
    if payload.active is not None:
        user.active = payload.active
    if payload.password is not None:
        user.password_hash = hash_password(payload.password)
    if payload.role_names is not None:
        user.roles = _resolve_roles(db, payload.role_names)
    db.flush()
    record_audit(db, actor, "users.update", "user", user.id, after={"username": user.username})
    db.commit()
    return serialize_user(user)
