"""项目文档接口表中的角色与权限接口：/api/v1/roles、/api/v1/permissions。

与 /api/v1/users/roles、/api/v1/users/permissions 使用同一套 services/rbac.py 逻辑。
"""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from ...models.user import Role, User
from ...schemas.user import RoleCreate, RoleUpdate
from ...services.rbac import (
    create_role,
    list_permissions,
    list_roles,
    serialize_role,
    update_role,
)
from ..deps import get_db, require_permission

router = APIRouter(tags=["rbac"])

_permission_guard = require_permission("users.manage")


@router.get("/roles")
def get_roles(db: Session = Depends(get_db), _: User = Depends(_permission_guard)) -> list[dict]:
    return list_roles(db)


@router.post("/roles", status_code=201)
def post_role(
    payload: RoleCreate,
    db: Session = Depends(get_db),
    actor: User = Depends(_permission_guard),
) -> dict:
    return serialize_role(create_role(db, payload, actor))


@router.get("/roles/{role_id}")
def get_role(
    role_id: str,
    db: Session = Depends(get_db),
    _: User = Depends(_permission_guard),
) -> dict:
    role = db.get(Role, role_id)
    if role is None:
        raise HTTPException(status_code=404, detail={"code": "NOT_FOUND", "message": "角色不存在"})
    return serialize_role(role)


@router.put("/roles/{role_id}")
def put_role(
    role_id: str,
    payload: RoleUpdate,
    db: Session = Depends(get_db),
    actor: User = Depends(_permission_guard),
) -> dict:
    role = db.get(Role, role_id)
    if role is None:
        raise HTTPException(status_code=404, detail={"code": "NOT_FOUND", "message": "角色不存在"})
    updated = update_role(
        db,
        role,
        description=payload.description,
        permission_names=payload.permission_names,
        actor=actor,
    )
    return serialize_role(updated)


@router.get("/permissions")
def get_permissions(db: Session = Depends(get_db), _: User = Depends(_permission_guard)) -> list[dict]:
    return list_permissions(db)
