"""项目文档接口表中的运输任务接口：/api/v1/mission-tasks。

与 /missions 共用 services/tasks.py，行为一致。
"""
import json
from datetime import datetime, timezone
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from ...core.pagination import run_list
from ...models import MapModel, MissionTask, Robot, Route, User
from ...schemas.tasks import MissionTaskCreate, MissionTaskUpdate
from ...services.ops import notify_users, record_audit
from ...services.tasks import serialize_mission, execution_record
from ..deps import get_db, require_permission

router = APIRouter(prefix="/mission-tasks", tags=["mission-tasks"])


def _get_task(db: Session, task_id: str) -> MissionTask:
    task = db.get(MissionTask, task_id)
    if task is None:
        raise HTTPException(status_code=404, detail={"code": "NOT_FOUND", "message": "运输任务不存在"})
    return task


def _validate_refs(
    db: Session,
    robot_id: str | None,
    map_id: str | None,
    route_id: str | None,
) -> None:
    if robot_id and db.get(Robot, robot_id) is None:
        raise HTTPException(status_code=400, detail={"code": "BAD_REQUEST", "message": "机器人不存在"})
    if map_id and db.get(MapModel, map_id) is None:
        raise HTTPException(status_code=400, detail={"code": "BAD_REQUEST", "message": "地图不存在"})
    if route_id and db.get(Route, route_id) is None:
        raise HTTPException(status_code=400, detail={"code": "BAD_REQUEST", "message": "路线不存在"})


@router.get("")
def list_mission_tasks(
    db: Session = Depends(get_db),
    _: User = Depends(require_permission("missions.read")),
    status: str | None = Query(default=None),
    robot_id: str | None = Query(default=None),
    keyword: str | None = Query(default=None),
    page: int | None = Query(default=None, ge=1),
    page_size: int | None = Query(default=None, ge=1, le=200),
):
    stmt = select(MissionTask).order_by(MissionTask.created_at.desc())
    if status:
        stmt = stmt.where(MissionTask.status == status)
    if robot_id:
        stmt = stmt.where(MissionTask.robot_id == robot_id)
    if keyword:
        like = f"%{keyword}%"
        stmt = stmt.where(
            or_(
                MissionTask.name.like(like),
                MissionTask.cargo_name.like(like),
                MissionTask.end_location.like(like),
            )
        )
    return run_list(db, stmt, serialize_mission, page, page_size)


@router.post("", status_code=201)
def create_mission_task(
    payload: MissionTaskCreate,
    db: Session = Depends(get_db),
    user: User = Depends(require_permission("missions.manage")),
) -> dict:
    _validate_refs(db, payload.robot_id, payload.map_id, payload.route_id)
    data = payload.model_dump()
    data["steps"] = json.dumps(data.pop("steps", []), ensure_ascii=False)
    cargo = data.get("cargo_name") or data.get("cargo") or ""
    origin = data.get("start_location") or data.get("origin") or ""
    destination = data.get("end_location") or data.get("destination") or ""
    data.update(
        {
            "cargo": cargo,
            "cargo_name": cargo,
            "origin": origin,
            "start_location": origin,
            "destination": destination,
            "end_location": destination,
            "status": data.get("status") or "queued",
        }
    )
    task = MissionTask(id=str(uuid4()), created_by=user.id, **data)
    db.add(task)
    db.flush()
    record_audit(db, user, "missions.create", "mission", task.id, after=serialize_mission(task))
    notify_users(db, kind="mission", title="运输任务已创建", body=task.name, ref_id=task.id)
    db.commit()
    return serialize_mission(task)


@router.get("/{task_id}")
def get_mission_task(
    task_id: str,
    db: Session = Depends(get_db),
    _: User = Depends(require_permission("missions.read")),
) -> dict:
    return serialize_mission(_get_task(db, task_id))


@router.put("/{task_id}")
def update_mission_task(
    task_id: str,
    payload: MissionTaskUpdate,
    db: Session = Depends(get_db),
    user: User = Depends(require_permission("missions.manage")),
) -> dict:
    task = _get_task(db, task_id)
    if execution_record(task):
        raise HTTPException(status_code=409, detail={"code": "EXECUTION_BOUND", "message": "实车执行任务不允许手工改写状态或坐标"})
    before = serialize_mission(task)
    data = payload.model_dump(exclude_unset=True)
    if "steps" in data:
        data["steps"] = json.dumps(data["steps"] or [], ensure_ascii=False)
    _validate_refs(db, data.get("robot_id"), data.get("map_id"), data.get("route_id"))
    for key, value in data.items():
        setattr(task, key, value)
    # 保持文档字段与旧字段同步
    if "cargo_name" in data:
        task.cargo = task.cargo_name
    if "start_location" in data:
        task.origin = task.start_location
    if "end_location" in data:
        task.destination = task.end_location
    task.updated_at = datetime.now(timezone.utc)
    db.flush()
    record_audit(
        db, user, "missions.update", "mission", task.id, before=before, after=serialize_mission(task)
    )
    db.commit()
    return serialize_mission(task)
