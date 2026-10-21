import json
from datetime import datetime, timezone
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from ...core.pagination import run_list
from ...gateway import ALLOWED_COMMANDS, get_robot_gateway
from ...models import AppSetting
from ...models.core import Robot
from ...models.user import User
from ...schemas.robot import EmergencyStopIn, RobotControlIn, RobotCreate, RobotUpdate
from ...services.ops import notify_users, record_audit
from ...services.realtime import get_realtime_store
from ...services.robots import serialize_robot, status_payload
from ...services.ws_manager import robot_manager
from ..deps import get_db, require_any_permission, require_permission

router = APIRouter(prefix="/robots", tags=["robots"])


def _get_robot(db: Session, robot_id: str) -> Robot:
    robot = db.get(Robot, robot_id)
    if robot is None:
        raise HTTPException(status_code=404, detail={"code": "NOT_FOUND", "message": "机器人不存在"})
    return robot


def _gateway_base_url(db: Session) -> str:
    """系统设置中的车端地址优先，其次使用环境配置。"""
    overrides = {
        item.key: item.value for item in db.execute(select(AppSetting)).scalars().all()
    }
    return overrides.get("robot_web_url") or overrides.get("robot_gateway_url") or ""


async def _broadcast_robot(robot_id: str) -> None:
    store = get_realtime_store()
    status = store.get_status(robot_id) or {}
    await robot_manager.broadcast(
        {
            "type": "robot_status",
            "robot_id": robot_id,
            "status": {**status, "robot_id": robot_id},
        },
        room=robot_id,
    )


@router.get("")
def list_robots(
    db: Session = Depends(get_db),
    _: User = Depends(require_permission("robots.read")),
    status: str | None = Query(default=None),
    keyword: str | None = Query(default=None),
    page: int | None = Query(default=None, ge=1),
    page_size: int | None = Query(default=None, ge=1, le=200),
):
    stmt = select(Robot).order_by(Robot.name)
    if status:
        stmt = stmt.where(Robot.status == status)
    if keyword:
        like = f"%{keyword}%"
        stmt = stmt.where(or_(Robot.name.like(like), Robot.serial.like(like), Robot.robot_code.like(like)))
    statuses = get_realtime_store().all_statuses()
    return run_list(
        db,
        stmt,
        lambda robot: serialize_robot(robot, statuses.get(robot.id)),
        page,
        page_size,
    )


@router.post("", status_code=201)
def create_robot(
    payload: RobotCreate,
    db: Session = Depends(get_db),
    user: User = Depends(require_any_permission("robots.manage", "robots.control")),
) -> dict:
    serial = payload.serial or payload.robot_code
    if not serial:
        raise HTTPException(
            status_code=400,
            detail={"code": "BAD_REQUEST", "message": "必须提供 robot_code 或 serial"},
        )
    exists = db.execute(select(Robot).where(Robot.serial == serial)).scalar_one_or_none()
    if exists:
        raise HTTPException(status_code=409, detail={"code": "CONFLICT", "message": "机器人编号已存在"})
    data = payload.model_dump()
    data["serial"] = serial
    data["robot_code"] = payload.robot_code or serial
    for key in ("position", "network"):
        data[key] = json.dumps(data[key] or {}, ensure_ascii=False)
    now = datetime.now(timezone.utc)
    robot = Robot(id=str(uuid4()), created_at=now, updated_at=now, **data)
    db.add(robot)
    db.flush()
    record_audit(db, user, "robots.create", "robot", robot.id, after=serialize_robot(robot))
    db.commit()
    return serialize_robot(robot)


@router.get("/{robot_id}")
def get_robot(
    robot_id: str,
    db: Session = Depends(get_db),
    _: User = Depends(require_permission("robots.read")),
) -> dict:
    robot = _get_robot(db, robot_id)
    return serialize_robot(robot, get_realtime_store().get_status(robot_id))


@router.put("/{robot_id}")
def update_robot(
    robot_id: str,
    payload: RobotUpdate,
    db: Session = Depends(get_db),
    user: User = Depends(require_any_permission("robots.manage", "robots.control")),
) -> dict:
    robot = _get_robot(db, robot_id)
    before = serialize_robot(robot)
    data = payload.model_dump(exclude_unset=True)
    for key in ("position", "network"):
        if key in data:
            data[key] = json.dumps(data[key] or {}, ensure_ascii=False)
    if data.get("robot_code") == "":
        data.pop("robot_code")
    for key, value in data.items():
        setattr(robot, key, value)
    robot.updated_at = datetime.now(timezone.utc)
    db.flush()
    record_audit(
        db, user, "robots.update", "robot", robot.id, before=before, after=serialize_robot(robot)
    )
    db.commit()
    return serialize_robot(robot, get_realtime_store().get_status(robot_id))


@router.get("/{robot_id}/status")
def robot_status(
    robot_id: str,
    db: Session = Depends(get_db),
    _: User = Depends(require_permission("robots.read")),
) -> dict:
    robot = _get_robot(db, robot_id)
    store = get_realtime_store()
    return status_payload(robot, store.get_status(robot_id), store.backend)


@router.post("/{robot_id}/control")
async def robot_control(
    robot_id: str,
    payload: RobotControlIn,
    db: Session = Depends(get_db),
    user: User = Depends(require_permission("robots.control")),
) -> dict:
    robot = _get_robot(db, robot_id)
    store = get_realtime_store()
    current = store.get_status(robot_id) or {}
    if current.get("emergency_stop") and payload.command != "stop":
        raise HTTPException(
            status_code=409,
            detail={"code": "ROBOT_ESTOP", "message": "机器人处于急停状态，请先解除急停"},
        )
    if payload.command not in ALLOWED_COMMANDS:
        raise HTTPException(
            status_code=400,
            detail={
                "code": "BAD_REQUEST",
                "message": f"不支持的控制指令：{payload.command}",
                "allowed": sorted(ALLOWED_COMMANDS),
            },
        )

    gateway = get_robot_gateway(_gateway_base_url(db) or None)
    result = await gateway.send_command(
        robot_id,
        payload.command,
        speed=payload.speed,
        params=payload.params,
        robot_code=robot.robot_code or robot.serial,
    )

    store.add_activity(
        robot_id,
        {
            "kind": "control",
            "title": f"控制指令 {payload.command}",
            "body": result["detail"],
        },
    )
    record_audit(
        db,
        user,
        "robots.control",
        "robot",
        robot_id,
        after={"command": payload.command, "speed": payload.speed, "ok": result["ok"]},
    )
    db.commit()
    await _broadcast_robot(robot_id)
    store = get_realtime_store()
    return {
        "ok": result["ok"],
        "robot_id": robot_id,
        "command": payload.command,
        "speed": payload.speed,
        "gateway": {
            "mode": result["gateway"],
            "target": result["target"],
            "detail": result["detail"],
            "command": result["command"],
            "response": result["response"],
        },
        "robot": serialize_robot(robot, store.get_status(robot_id)),
    }


@router.post("/{robot_id}/emergency-stop")
async def robot_emergency_stop(
    robot_id: str,
    payload: EmergencyStopIn,
    db: Session = Depends(get_db),
    user: User = Depends(require_permission("robots.control")),
) -> dict:
    robot = _get_robot(db, robot_id)
    store = get_realtime_store()
    gateway = get_robot_gateway(_gateway_base_url(db) or None)
    result = await gateway.emergency_stop(
        robot_id,
        enabled=payload.enabled,
        reason=payload.reason,
        robot_code=robot.robot_code or robot.serial,
    )

    store.add_activity(
        robot_id,
        {
            "kind": "safety",
            "title": ("急停请求已下发" if payload.enabled else "解除急停请求已下发") if result["ok"] else "急停请求下发失败",
            "body": payload.reason or result["detail"],
        },
    )
    record_audit(
        db,
        user,
        "robots.emergency_stop" if payload.enabled else "robots.emergency_stop_release",
        "robot",
        robot_id,
        after={"enabled": payload.enabled, "reason": payload.reason, "ok": result["ok"]},
    )
    notify_users(
        db,
        kind="robot",
        title=("急停请求已下发" if payload.enabled else "解除急停请求已下发") if result["ok"] else "急停请求下发失败",
        body=f"{robot.name} {payload.reason}".strip(),
        ref_id=robot.id,
    )
    db.commit()
    await _broadcast_robot(robot_id)
    return {
        "ok": result["ok"],
        "robot_id": robot_id,
        "enabled": payload.enabled,
        "reason": payload.reason,
        "gateway": {
            "mode": result["gateway"],
            "target": result["target"],
            "detail": result["detail"],
            "command": result["command"],
        },
        "robot": serialize_robot(robot, get_realtime_store().get_status(robot_id)),
    }


@router.get("/{robot_id}/activity")
def robot_activity(
    robot_id: str,
    db: Session = Depends(get_db),
    _: User = Depends(require_permission("robots.read")),
) -> list[dict]:
    _get_robot(db, robot_id)
    return get_realtime_store().get_activity(robot_id)
