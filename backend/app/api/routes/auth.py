from datetime import timedelta
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from ...core.config import settings
from ...core.security import (
    create_access_token,
    create_refresh_token,
    decode_token,
    hash_password,
    verify_password,
)
from ...models.user import Role, User
from ...schemas.auth import LoginRequest, RefreshRequest, RegisterRequest, RoleOut, TokenOut, UserOut
from ...services.ops import record_audit
from ..deps import get_current_user, get_db

router = APIRouter(prefix="/auth", tags=["auth"])


def _role_out(role: Role | None) -> RoleOut | None:
    if role is None:
        return None
    return RoleOut.model_validate(role)


def _user_out(user: User) -> UserOut:
    role = user.roles[0] if user.roles else None
    data = UserOut.model_validate(user).model_dump()
    data["role"] = _role_out(role)
    return UserOut(**data)


def _issue_tokens(user_id: str) -> tuple[str, str]:
    access = create_access_token(
        user_id,
        settings.jwt_secret,
        expires_delta=timedelta(minutes=settings.access_token_expire_minutes),
    )
    refresh = create_refresh_token(
        user_id,
        settings.jwt_secret,
        expires_delta=timedelta(days=settings.refresh_token_expire_days),
    )
    return access, refresh


@router.post("/register", response_model=TokenOut, status_code=201)
def register(payload: RegisterRequest, db: Session = Depends(get_db)) -> TokenOut:
    """Public signup is restricted to the seeded read-only viewer role."""
    username = payload.username.lower()
    if db.execute(select(User).where(User.username == username)).scalar_one_or_none():
        raise HTTPException(status_code=409, detail={"code": "CONFLICT", "message": "用户名已存在"})
    role = db.execute(select(Role).where(Role.name == "viewer")).scalar_one_or_none()
    if role is None:
        raise HTTPException(status_code=503, detail={"code": "SETUP_REQUIRED", "message": "注册暂不可用，请联系管理员初始化系统"})
    user = User(
        id=str(uuid4()),
        username=username,
        password_hash=hash_password(payload.password),
        display_name=payload.display_name.strip() or username,
        email=payload.email,
        active=True,
    )
    user.roles = [role]
    db.add(user)
    try:
        db.flush()
        record_audit(db, user, "auth.register", "user", user.id, after={"username": username})
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=409, detail={"code": "CONFLICT", "message": "用户名已存在"})
    access, refresh = _issue_tokens(user.id)
    return TokenOut(access_token=access, refresh_token=refresh, user=_user_out(user))


@router.post("/login", response_model=TokenOut)
def login(payload: LoginRequest, db: Session = Depends(get_db)) -> TokenOut:
    user = db.execute(select(User).where(User.username == payload.username)).scalar_one_or_none()
    if user is None or not verify_password(payload.password, user.password_hash):
        record_audit(
            db,
            None,
            "auth.login_failed",
            "user",
            None,
            after={"username": payload.username},
        )
        db.commit()
        raise HTTPException(
            status_code=401,
            detail={"code": "AUTH_INVALID", "message": "用户名或密码错误"},
        )
    if not user.active:
        record_audit(db, None, "auth.login_rejected", "user", user.id, after={"reason": "inactive"})
        db.commit()
        raise HTTPException(
            status_code=403,
            detail={"code": "AUTH_INVALID", "message": "账号已停用"},
        )
    record_audit(db, user, "auth.login", "user", user.id, after={"username": user.username})
    db.commit()
    access, refresh = _issue_tokens(user.id)
    return TokenOut(
        access_token=access,
        refresh_token=refresh,
        user=_user_out(user),
    )


@router.post("/refresh", response_model=TokenOut)
def refresh(payload: RefreshRequest, db: Session = Depends(get_db)) -> TokenOut:
    try:
        data = decode_token(payload.refresh_token, settings.jwt_secret)
    except ValueError:
        raise HTTPException(
            status_code=401,
            detail={"code": "AUTH_INVALID", "message": "刷新令牌无效或已过期"},
        )
    if data.get("type") != "refresh":
        raise HTTPException(
            status_code=401,
            detail={"code": "AUTH_INVALID", "message": "令牌类型错误"},
        )
    user = db.get(User, data.get("sub"))
    if user is None or not user.active:
        raise HTTPException(
            status_code=401,
            detail={"code": "AUTH_INVALID", "message": "账号不存在或已停用"},
        )
    access, refresh_token = _issue_tokens(user.id)
    return TokenOut(
        access_token=access,
        refresh_token=refresh_token,
        user=_user_out(user),
    )


@router.get("/me", response_model=UserOut)
def me(user: User = Depends(get_current_user)) -> UserOut:
    return _user_out(user)


@router.post("/logout")
def logout(
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict:
    """无状态 JWT：服务端只记录审计，客户端丢弃本地令牌即可。"""
    record_audit(db, user, "auth.logout", "user", user.id)
    db.commit()
    return {"ok": True}
