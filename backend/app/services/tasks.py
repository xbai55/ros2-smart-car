"""巡检任务与运输任务的共享业务逻辑。

`/patrols` + `/patrols/{id}/actions`（现有 Flutter 控制台使用）与文档中的
`/patrol-tasks` + `/patrol-tasks/{id}/start|stop` 共用这里的序列化与状态机，
避免两套实现产生分歧。
"""
from __future__ import annotations

import json
from datetime import datetime, timezone

from fastapi import HTTPException
from sqlalchemy.orm import Session

from ..models import MissionTask, PatrolTask, User
from .ops import json_loads, notify_users, record_audit

PATROL_STATUSES = ("pending", "running", "paused", "completed", "failed", "cancelled")
MISSION_STATUSES = ("queued", "dispatched", "transporting", "completed", "failed", "cancelled")

PATROL_ACTIONS: dict[str, dict[str, str]] = {
    "start": {"pending": "running", "paused": "running"},
    "pause": {"running": "paused"},
    "resume": {"paused": "running"},
    "cancel": {"pending": "cancelled", "running": "cancelled", "paused": "cancelled"},
    "complete": {"running": "completed"},
    "fail": {"pending": "failed", "running": "failed", "paused": "failed"},
}

MISSION_ACTIONS: dict[str, dict[str, str]] = {
    "dispatch": {"queued": "dispatched"},
    "pickup": {"dispatched": "transporting"},
    "transporting": {"dispatched": "transporting"},
    "handover": {"transporting": "completed"},
    "complete": {"transporting": "completed"},
    "cancel": {
        "queued": "cancelled",
        "dispatched": "cancelled",
        "transporting": "cancelled",
    },
    "fail": {"queued": "failed", "dispatched": "failed", "transporting": "failed"},
}


def _iso(value: datetime | None) -> str | None:
    return value.isoformat() if value else None


def execution_record(task):
    values = json_loads(task.steps if isinstance(task, MissionTask) else task.inspection_points, [])
    return next((v["execution"] for v in values if isinstance(v, dict) and isinstance(v.get("execution"), dict)), None)


def serialize_patrol(task: PatrolTask) -> dict:
    return {
        "execution": execution_record(task),
        "id": task.id,
        "name": task.name,
        "description": task.description,
        "robot_id": task.robot_id,
        "map_id": task.map_id,
        "route_id": task.route_id,
        "target_area": task.target_area,
        "status": task.status,
        "priority": task.priority,
        "progress": task.progress,
        "inspection_points": json_loads(task.inspection_points),
        "created_by": task.created_by,
        "started_at": _iso(task.started_at),
        "completed_at": _iso(task.completed_at),
        "created_at": _iso(task.created_at),
        "updated_at": _iso(task.updated_at),
    }


def serialize_mission(task: MissionTask) -> dict:
    return {
        "execution": execution_record(task),
        "id": task.id,
        "name": task.name,
        "description": task.description,
        "robot_id": task.robot_id,
        "map_id": task.map_id,
        "route_id": task.route_id,
        "status": task.status,
        "progress": task.progress,
        "cargo": task.cargo or task.cargo_name,
        "cargo_name": task.cargo_name or task.cargo,
        "origin": task.origin or task.start_location,
        "destination": task.destination or task.end_location,
        "start_location": task.start_location or task.origin,
        "end_location": task.end_location or task.destination,
        "pickup_code": task.pickup_code,
        "steps": json_loads(task.steps),
        "created_by": task.created_by,
        "started_at": _iso(task.started_at),
        "completed_at": _iso(task.completed_at),
        "pickup_confirmed_at": _iso(task.pickup_confirmed_at),
        "handover_confirmed_at": _iso(task.handover_confirmed_at),
        "created_at": _iso(task.created_at),
        "updated_at": _iso(task.updated_at),
    }


def _conflict(action: str, status: str) -> HTTPException:
    return HTTPException(
        status_code=409,
        detail={"code": "STATE_CONFLICT", "message": f"当前状态 {status} 不允许 {action}"},
    )


def apply_patrol_action(db: Session, task: PatrolTask, action: str, user: User) -> dict:
    if execution_record(task):
        raise HTTPException(status_code=409, detail={"code": "EXECUTION_BOUND", "message": "该任务已绑定实车，请通过执行控制操作"})
    if action not in PATROL_ACTIONS:
        raise HTTPException(
            status_code=400,
            detail={"code": "BAD_REQUEST", "message": f"不支持的动作：{action}"},
        )
    allowed = PATROL_ACTIONS[action]
    if task.status not in allowed:
        raise _conflict(action, task.status)

    before = serialize_patrol(task)
    task.status = allowed[task.status]
    now = datetime.now(timezone.utc)
    if action in ("start", "resume"):
        task.started_at = task.started_at or now
    if action == "complete":
        task.progress = 100.0
        task.completed_at = now
    task.updated_at = now
    record_audit(
        db, user, f"patrols.{action}", "patrol", task.id, before=before, after=serialize_patrol(task)
    )
    notify_users(db, kind="patrol", title=f"巡检任务{action}", body=task.name, ref_id=task.id)
    db.commit()
    return serialize_patrol(task)


def apply_mission_action(db: Session, task: MissionTask, action: str, user: User) -> dict:
    if execution_record(task):
        raise HTTPException(status_code=409, detail={"code": "EXECUTION_BOUND", "message": "该任务已绑定实车，请通过执行控制操作"})
    if action not in MISSION_ACTIONS:
        raise HTTPException(
            status_code=400,
            detail={"code": "BAD_REQUEST", "message": f"不支持的动作：{action}"},
        )
    allowed = MISSION_ACTIONS[action]
    if task.status not in allowed:
        raise _conflict(action, task.status)

    before = serialize_mission(task)
    task.status = allowed[task.status]
    now = datetime.now(timezone.utc)
    if action in ("dispatch", "pickup", "transporting"):
        task.started_at = task.started_at or now
    if action == "pickup":
        task.pickup_confirmed_at = now
        task.progress = max(task.progress, 50.0)
    if action in ("handover", "complete"):
        task.handover_confirmed_at = now
        task.progress = 100.0
        task.completed_at = now
    task.updated_at = now
    record_audit(
        db, user, f"missions.{action}", "mission", task.id, before=before, after=serialize_mission(task)
    )
    notify_users(db, kind="mission", title=f"运输任务{action}", body=task.name, ref_id=task.id)
    db.commit()
    return serialize_mission(task)


def dump_json(value) -> str:
    return json.dumps(value, ensure_ascii=False)
