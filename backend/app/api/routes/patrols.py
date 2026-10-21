import json
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from ...core.pagination import run_list
from ...models import PatrolTask, Robot, Route, User
from ...schemas.ops import PatrolAction, PatrolCreate
from ...services.ops import notify_users, record_audit
from ...services.tasks import apply_patrol_action, serialize_patrol
from ..deps import get_db, require_permission

router = APIRouter(prefix="/patrols", tags=["patrols"])


def _validate_refs(db: Session, robot_id: str | None, route_id: str | None) -> None:
    if robot_id and db.get(Robot, robot_id) is None:
        raise HTTPException(status_code=400, detail={"code": "BAD_REQUEST", "message": "机器人不存在"})
    if route_id and db.get(Route, route_id) is None:
        raise HTTPException(status_code=400, detail={"code": "BAD_REQUEST", "message": "路线不存在"})


@router.get("")
def list_patrols(
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
def create_patrol(
    payload: PatrolCreate,
    db: Session = Depends(get_db),
    user: User = Depends(require_permission("patrol.manage")),
) -> dict:
    _validate_refs(db, payload.robot_id, payload.route_id)
    data = payload.model_dump()
    data["inspection_points"] = json.dumps(data.pop("inspection_points", []), ensure_ascii=False)
    task = PatrolTask(id=str(uuid4()), created_by=user.id, **data)
    db.add(task)
    db.flush()
    record_audit(db, user, "patrols.create", "patrol", task.id, after=serialize_patrol(task))
    notify_users(db, kind="patrol", title="巡检任务已创建", body=task.name, ref_id=task.id)
    db.commit()
    return serialize_patrol(task)


@router.get("/{patrol_id}")
def get_patrol(
    patrol_id: str,
    db: Session = Depends(get_db),
    _: User = Depends(require_permission("patrol.read")),
) -> dict:
    task = db.get(PatrolTask, patrol_id)
    if task is None:
        raise HTTPException(status_code=404, detail={"code": "NOT_FOUND", "message": "巡检任务不存在"})
    return serialize_patrol(task)


@router.post("/{patrol_id}/actions")
def patrol_action(
    patrol_id: str,
    payload: PatrolAction,
    db: Session = Depends(get_db),
    user: User = Depends(require_permission("patrol.manage")),
) -> dict:
    task = db.get(PatrolTask, patrol_id)
    if task is None:
        raise HTTPException(status_code=404, detail={"code": "NOT_FOUND", "message": "巡检任务不存在"})
    return apply_patrol_action(db, task, payload.action, user)
