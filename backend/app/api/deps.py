from typing import Callable

from fastapi import Depends, Header, HTTPException
from sqlalchemy.orm import Session

from ..core.config import settings
from ..core.security import decode_token
from ..db.session import SessionLocal
from ..models.user import User


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def _error(status: int, code: str, message: str) -> HTTPException:
    return HTTPException(status_code=status, detail={"code": code, "message": message})


def get_current_user(
    authorization: str = Header(default=None),
    db: Session = Depends(get_db),
) -> User:
    if not authorization or not authorization.startswith("Bearer "):
        raise _error(401, "AUTH_INVALID", "缺少访问令牌")
    token = authorization[7:]
    try:
        payload = decode_token(token, settings.jwt_secret)
    except ValueError:
        raise _error(401, "AUTH_INVALID", "访问令牌无效或已过期")
    if payload.get("type") != "access":
        raise _error(401, "AUTH_INVALID", "令牌类型错误")
    user = db.get(User, payload.get("sub"))
    if user is None or not user.active:
        raise _error(401, "AUTH_INVALID", "账号不存在或已停用")
    return user


def require_permission(permission: str) -> Callable:
    def checker(user: User = Depends(get_current_user)) -> User:
        if permission not in user.permissions:
            raise _error(403, "FORBIDDEN", f"缺少权限：{permission}")
        return user

    return checker


def require_any_permission(*permissions: str) -> Callable:
    """满足任意一个权限即可（用于兼容旧角色配置中缺少新权限的情况）。"""

    def checker(user: User = Depends(get_current_user)) -> User:
        if not permissions or user.permissions.isdisjoint(permissions):
            raise _error(403, "FORBIDDEN", f"缺少权限：{' / '.join(permissions)}")
        return user

    return checker
