from uuid import uuid4

from .core.security import hash_password
from .db.base import Base
from .db.migrate import ensure_schema
from .db.session import SessionLocal, engine
from .models import (
    AppSetting,
    Permission,
    Role,
    User,
)

PERMISSIONS = {
    "robots.read": "查看机器人状态",
    "robots.control": "手动控制与解除急停",
    "robots.manage": "管理机器人档案",
    "maps.read": "查看地图",
    "maps.manage": "管理地图",
    "routes.read": "查看路线",
    "routes.manage": "管理路线",
    "patrol.read": "查看巡检任务",
    "patrol.manage": "创建与派发巡检任务",
    "missions.read": "查看运输任务",
    "missions.manage": "创建与派发运输任务",
    "incidents.read": "查看异常事件",
    "incidents.manage": "处理异常事件",
    "analytics.read": "查看统计分析",
    "users.manage": "管理用户与角色",
    "settings.read": "查看系统设置",
    "settings.manage": "管理系统设置",
    "audit.read": "查看审计日志",
    "notifications.read": "查看通知",
}

ROLES = {
    "viewer": [
        "robots.read", "maps.read", "routes.read", "patrol.read",
        "missions.read", "incidents.read", "analytics.read",
        "notifications.read",
    ],
    "admin": list(PERMISSIONS.keys()),
    "operator": [
        "robots.read",
        "robots.control",
        "maps.read",
        "maps.manage",
        "routes.read",
        "routes.manage",
        "patrol.read",
        "patrol.manage",
        "missions.read",
        "missions.manage",
        "incidents.read",
        "incidents.manage",
        "analytics.read",
        "settings.read",
        "notifications.read",
    ],
    "auditor": [
        "robots.read",
        "maps.read",
        "routes.read",
        "patrol.read",
        "missions.read",
        "incidents.read",
        "analytics.read",
        "settings.read",
        "audit.read",
        "notifications.read",
    ],
}

USERS = {
    "admin": {"password": "admin123", "display_name": "系统管理员", "role": "admin"},
    "operator": {"password": "operator123", "display_name": "值班操作员", "role": "operator"},
    "auditor": {"password": "auditor123", "display_name": "审计员", "role": "auditor"},
}

def seed_session(db, *, users=None) -> None:
    existing = {p.name for p in db.query(Permission).all()}
    for name, description in PERMISSIONS.items():
        if name not in existing:
            db.add(Permission(id=str(uuid4()), name=name, description=description))
    db.flush()

    role_map = {}
    for role_name, perms in ROLES.items():
        role = db.query(Role).filter(Role.name == role_name).one_or_none()
        if role is None:
            role = Role(id=str(uuid4()), name=role_name, description=role_name)
            db.add(role)
        role.permissions = [
            db.query(Permission).filter(Permission.name == p).one() for p in perms
        ]
        role_map[role_name] = role

    for username, spec in (USERS if users is None else users).items():
        user = db.query(User).filter(User.username == username).one_or_none()
        if user is None:
            user = User(
                id=str(uuid4()),
                username=username,
                password_hash=hash_password(spec["password"]),
                display_name=spec["display_name"],
            )
            db.add(user)
        user.roles = [role_map[spec["role"]]]

    defaults = {
        "system_name": "InsightRover 智巡控制台",
        "robot_web_url": "",
        "robot_gateway_url": "",
        "video_service_url": "",
        "heartbeat_timeout_seconds": "30",
        "task_retry_limit": "3",
        "map_default_resolution": "0.05",
        "log_retention_days": "30",
    }
    existing_keys = {item.key for item in db.query(AppSetting).all()}
    for key, value in defaults.items():
        if key not in existing_keys:
            db.add(AppSetting(id=str(uuid4()), key=key, value=value))

    db.commit()


def seed() -> None:
    Base.metadata.create_all(bind=engine)
    ensure_schema(engine)
    db = SessionLocal()
    try:
        seed_session(db)
        print("initialized roles/permissions/users/settings")
    finally:
        db.close()


if __name__ == "__main__":
    seed()
