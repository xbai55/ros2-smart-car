import json
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from ...core.pagination import run_list
from ...models import MissionTask, Robot, Route, User
from ...schemas.ops import MissionAction, MissionCreate
from ...services.ops import notify_users, record_audit
from ...services.tasks import apply_mission_action, serialize_mission
from ..deps import get_db, require_permission

router = APIRouter(prefix="/missions", tags=["missions"])


def _validate_refs(db: Session, robot_id: str | None, route_id: str | None) -> None:
    if robot_id and db.get(Robot, robot_id) is None:
        raise HTTPException(status_code=400, detail={"code": "BAD_REQUEST", "message": "机器人不存在"})
    if route_id and db.get(Route, route_id) is None:
        raise HTTPException(status_code=400, detail={"code": "BAD_REQUEST", "message": "路线不存在"})


@router.get("")
def list_missions(
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
                MissionTask.cargo.like(like),
                MissionTask.destination.like(like),
            )
        )
    return run_list(db, stmt, serialize_mission, page, page_size)


@router.post("", status_code=201)
def create_mission(
    payload: MissionCreate,
    db: Session = Depends(get_db),
    user: User = Depends(require_permission("missions.manage")),
) -> dict:
    _validate_refs(db, payload.robot_id, payload.route_id)
    data = payload.model_dump()
    data["steps"] = json.dumps(data.pop("steps", []), ensure_ascii=False)
    # 文档字段名与旧字段名保持一致，避免两条接口读出不同结果
    data["cargo_name"] = data.get("cargo", "")
    data["start_location"] = data.get("origin", "")
    data["end_location"] = data.get("destination", "")
    task = MissionTask(id=str(uuid4()), created_by=user.id, **data)
    db.add(task)
    db.flush()
    record_audit(db, user, "missions.create", "mission", task.id, after=serialize_mission(task))
    notify_users(db, kind="mission", title="运输任务已创建", body=task.name, ref_id=task.id)
    db.commit()
    return serialize_mission(task)


@router.get("/{mission_id}")
def get_mission(
    mission_id: str,
    db: Session = Depends(get_db),
    _: User = Depends(require_permission("missions.read")),
) -> dict:
    task = db.get(MissionTask, mission_id)
    if task is None:
        raise HTTPException(status_code=404, detail={"code": "NOT_FOUND", "message": "运输任务不存在"})
    return serialize_mission(task)


@router.post("/{mission_id}/actions")
def mission_action(
    mission_id: str,
    payload: MissionAction,
    db: Session = Depends(get_db),
    user: User = Depends(require_permission("missions.manage")),
) -> dict:
    task = db.get(MissionTask, mission_id)
    if task is None:
        raise HTTPException(status_code=404, detail={"code": "NOT_FOUND", "message": "运输任务不存在"})
    return apply_mission_action(db, task, payload.action, user)
