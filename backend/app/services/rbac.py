"""用户 / 角色 / 权限的共享逻辑（RBAC）。"""
from __future__ import annotations

from uuid import uuid4

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models.user import Permission, Role, User
from ..schemas.user import RoleCreate
from .ops import record_audit


def serialize_permission(permission: Permission) -> dict:
    return {
        "id": permission.id,
        "name": permission.name,
        "description": permission.description,
    }


def serialize_role(role: Role) -> dict:
    return {
        "id": role.id,
        "name": role.name,
        "description": role.description,
        "permissions": [serialize_permission(p) for p in role.permissions],
    }


def serialize_user(user: User) -> dict:
    return {
        "id": user.id,
        "username": user.username,
        "display_name": user.display_name,
        "email": user.email,
        "active": user.active,
        "roles": [r.name for r in user.roles],
        "permissions": sorted(user.permissions),
    }


def resolve_permissions(db: Session, names: list[str]) -> list[Permission]:
    unique = set(names)
    if not unique:
        return []
    permissions = db.execute(select(Permission).where(Permission.name.in_(unique))).scalars().all()
    if len(permissions) != len(unique):
        missing = unique - {p.name for p in permissions}
        raise HTTPException(
            status_code=400,
            detail={"code": "BAD_REQUEST", "message": f"权限不存在：{', '.join(sorted(missing))}"},
        )
    return list(permissions)


def list_roles(db: Session) -> list[dict]:
    roles = db.execute(select(Role).order_by(Role.name)).scalars().all()
    return [serialize_role(r) for r in roles]


def list_permissions(db: Session) -> list[dict]:
    permissions = db.execute(select(Permission).order_by(Permission.name)).scalars().all()
    return [serialize_permission(p) for p in permissions]


def create_role(db: Session, payload: RoleCreate, actor: User | None) -> Role:
    exists = db.execute(select(Role).where(Role.name == payload.name)).scalar_one_or_none()
    if exists:
        raise HTTPException(status_code=409, detail={"code": "CONFLICT", "message": "角色已存在"})
    role = Role(
        id=str(uuid4()),
        name=payload.name,
        description=payload.description,
        permissions=resolve_permissions(db, payload.permission_names),
    )
    db.add(role)
    db.flush()
    record_audit(db, actor, "roles.create", "role", role.id, after={"name": role.name})
    db.commit()
    return role


def update_role(
    db: Session,
    role: Role,
    *,
    description: str | None = None,
    permission_names: list[str] | None = None,
    actor: User | None = None,
) -> Role:
    before = serialize_role(role)
    if description is not None:
        role.description = description
    if permission_names is not None:
        role.permissions = resolve_permissions(db, permission_names)
    db.flush()
    record_audit(
        db, actor, "roles.update", "role", role.id, before=before, after=serialize_role(role)
    )
    db.commit()
    return role
