"""项目文档接口表中的巡检任务接口：/api/v1/patrol-tasks。

与 /patrols 共用 services/tasks.py 中的序列化与状态机，两条路径行为一致。
"""
import json
from datetime import datetime, timezone
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from ...core.pagination import run_list
from ...models import MapModel, PatrolTask, Robot, Route, User
from ...schemas.tasks import PatrolTaskCreate, PatrolTaskUpdate
from ...services.ops import notify_users, record_audit
from ...services.tasks import apply_patrol_action, serialize_patrol
from ..deps import get_db, require_permission

router = APIRouter(prefix="/patrol-tasks", tags=["patrol-tasks"])


def _get_task(db: Session, task_id: str) -> PatrolTask:
    task = db.get(PatrolTask, task_id)
    if task is None:
        raise HTTPException(status_code=404, detail={"code": "NOT_FOUND", "message": "巡检任务不存在"})
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
def list_patrol_tasks(
    db: Session = Depends(get_db),
    _: User = Depends(require_permission("patrol.read")),
    status: str | None = Query(default=None),
    robot_id: str | None = Query(default=None),
    keyword: str | None = Query(default=None),
    page: int | None = Query(default=None, ge=1),
    page_size: int | None = Query(default=None, ge=1, le=200),
):
    stmt = select(PatrolTask).order_by(PatrolTask.created_at.desc())
    if status:
        stmt = stmt.where(PatrolTask.status == status)
    if robot_id:
        stmt = stmt.where(PatrolTask.robot_id == robot_id)
    if keyword:
        like = f"%{keyword}%"
        stmt = stmt.where(or_(PatrolTask.name.like(like), PatrolTask.target_area.like(like)))
    return run_list(db, stmt, serialize_patrol, page, page_size)


@router.post("", status_code=201)
def create_patrol_task(
    payload: PatrolTaskCreate,
    db: Session = Depends(get_db),
    user: User = Depends(require_permission("patrol.manage")),
) -> dict:
    _validate_refs(db, payload.robot_id, payload.map_id, payload.route_id)
    data = payload.model_dump()
    data["inspection_points"] = json.dumps(data.pop("inspection_points", []), ensure_ascii=False)
    data["status"] = data.get("status") or "pending"
    task = PatrolTask(id=str(uuid4()), created_by=user.id, **data)
    db.add(task)
    db.flush()
    record_audit(db, user, "patrols.create", "patrol", task.id, after=serialize_patrol(task))
    notify_users(db, kind="patrol", title="巡检任务已创建", body=task.name, ref_id=task.id)
    db.commit()
    return serialize_patrol(task)


@router.get("/{task_id}")
def get_patrol_task(
    task_id: str,
    db: Session = Depends(get_db),
    _: User = Depends(require_permission("patrol.read")),
) -> dict:
    return serialize_patrol(_get_task(db, task_id))


@router.put("/{task_id}")
def update_patrol_task(
    task_id: str,
    payload: PatrolTaskUpdate,
    db: Session = Depends(get_db),
    user: User = Depends(require_permission("patrol.manage")),
) -> dict:
    task = _get_task(db, task_id)
    from ...services.tasks import execution_record
    if execution_record(task):
        raise HTTPException(status_code=409, detail={"code": "EXECUTION_BOUND", "message": "实车执行任务不允许手工改写状态或坐标"})
    before = serialize_patrol(task)
    data = payload.model_dump(exclude_unset=True)
    if "inspection_points" in data:
        data["inspection_points"] = json.dumps(data["inspection_points"] or [], ensure_ascii=False)
    _validate_refs(db, data.get("robot_id"), data.get("map_id"), data.get("route_id"))
    for key, value in data.items():
        setattr(task, key, value)
    task.updated_at = datetime.now(timezone.utc)
    db.flush()
    record_audit(
        db, user, "patrols.update", "patrol", task.id, before=before, after=serialize_patrol(task)
    )
    db.commit()
    return serialize_patrol(task)


@router.post("/{task_id}/start")
def start_patrol_task(
    task_id: str,
    db: Session = Depends(get_db),
    user: User = Depends(require_permission("patrol.manage")),
) -> dict:
    return apply_patrol_action(db, _get_task(db, task_id), "start", user)


@router.post("/{task_id}/stop")
def stop_patrol_task(
    task_id: str,
    db: Session = Depends(get_db),
    user: User = Depends(require_permission("patrol.manage")),
) -> dict:
    return apply_patrol_action(db, _get_task(db, task_id), "cancel", user)
