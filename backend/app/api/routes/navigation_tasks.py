"""Business tasks use vehicle-confirmed execution records, never optimistic arrival."""
import json
import hashlib
from datetime import datetime, timezone
from uuid import NAMESPACE_URL, uuid4, uuid5

from fastapi import APIRouter, Body, Depends, HTTPException
import httpx
from sqlalchemy import select, update
from sqlalchemy.orm import Session

from ...models import AppSetting, MissionTask, PatrolTask, Robot, MapModel, User
from ...gateway import get_robot_gateway
from ...services.ops import json_loads, record_audit
from ...services.tasks import serialize_mission, serialize_patrol
from ..deps import get_db, require_permission

router = APIRouter(prefix="/navigation-tasks", tags=["navigation-tasks"])


def _error(code, message):
    return HTTPException(status_code=code, detail={"code": "NAVIGATION_TASK", "message": message})


def execution(task):
    entries = json_loads(task.steps if isinstance(task, MissionTask) else task.inspection_points, [])
    return next((item["execution"] for item in entries if isinstance(item, dict) and isinstance(item.get("execution"), dict)), None)


def store_execution(db, task, value):
    """Compare-and-swap prevents a delayed poll from undoing cancellation."""
    model = type(task)
    field = "steps" if isinstance(task, MissionTask) else "inspection_points"
    for _ in range(4):
        db.refresh(task)
        previous = execution(task)
        if previous and previous.get("run_id") != value.get("run_id"):
            raise _error(409, "任务执行标识已变化")
        if previous:
            if previous.get("state") in {"completed", "cancelled", "failed"} and value["state"] != previous["state"]:
                return False
            if value.get("version", 0) < previous.get("version", 0) or value == previous:
                return False
        raw = getattr(task, field)
        entries = [item for item in json_loads(raw, []) if not isinstance(item, dict) or "execution" not in item]
        state = value["state"]
        if state in {"failed", "cancelled", "completed"}:
            status = state
        elif isinstance(task, MissionTask):
            status = "dispatched" if state in {"waiting_load", "prepared", "unconfirmed"} else "transporting"
        else:
            status = "paused" if state == "paused" else "pending" if state in {"prepared", "unconfirmed"} else "running"
        now = datetime.now(timezone.utc)
        changes = {field: json.dumps([*entries, {"execution": value}], ensure_ascii=False, allow_nan=False),
                   "status": status, "updated_at": now,
                   "progress": 100 if state == "completed" else min(95, 90 * value.get("completed_stops", 0) / max(1, value.get('total_stops', len(value.get("goals", [])))))}
        if state in {"planning", "running", "returning", "dwelling", "waiting_handover"}:
            changes["started_at"] = task.started_at or now
            if isinstance(task, MissionTask):
                changes["pickup_confirmed_at"] = task.pickup_confirmed_at or now
        if state == "completed":
            changes["completed_at"] = task.completed_at or now
            if isinstance(task, MissionTask):
                changes["handover_confirmed_at"] = task.handover_confirmed_at or now
        with db.no_autoflush:
            result = db.execute(update(model).where(model.id == task.id, getattr(model, field) == raw)
                                .values(**changes).execution_options(synchronize_session=False))
        db.expire(task)
        if result.rowcount == 1:
            db.refresh(task)
            return True
    raise _error(409, "任务状态同时发生变化，请刷新后重试")


def _task(db, kind, ident):
    model = MissionTask if kind == "delivery" else PatrolTask if kind == "patrol" else None
    item = db.get(model, ident) if model else None
    if item is None:
        raise _error(404, "任务不存在")
    return item


def _permission(user, kind, manage=True):
    permission = ("missions" if kind == "delivery" else "patrol") + (".manage" if manage else ".read")
    if permission not in user.permissions:
        raise _error(403, "没有此任务的操作权限")


def _gateway(db):
    setting = db.scalar(select(AppSetting).where(AppSetting.key == "robot_web_url"))
    return get_robot_gateway(setting.value if setting else None)


async def _call(db, path, payload=None, query=None):
    try:
        return await _gateway(db).navigation_request(path, payload, query=query)
    except httpx.HTTPStatusError as exc:
        try:
            message = str(exc.response.json().get("detail", "车端拒绝了操作"))
        except ValueError:
            message = "车端返回了无效响应"
        raise _error(409 if exc.response.status_code < 500 else 502, message) from exc
    except (httpx.HTTPError, RuntimeError, ValueError) as exc:
        raise _error(502, f"未能确认车端执行状态，请刷新核对：{exc}") from exc


@router.post("")
async def create_execution(payload: dict = Body(...), db: Session = Depends(get_db),
                           user: User = Depends(require_permission("robots.read"))):
    kind = payload.get("kind")
    if kind not in {"delivery", "patrol"}:
        raise _error(422, "任务类型无效")
    _permission(user, kind)
    run_id = payload.get("run_id")
    if not isinstance(run_id, str) or not 1 <= len(run_id) <= 128:
        raise _error(422, "任务请求标识无效")
    task_id = payload.get("task_id") or str(uuid5(NAMESPACE_URL, f"navigation:{kind}:{run_id}"))
    model = MissionTask if kind == "delivery" else PatrolTask
    item = db.get(model, task_id)
    if item is None:
        if payload.get("task_id"):
            raise _error(404, "原业务任务不存在")
        robot = db.get(Robot, payload.get("robot_id")) if payload.get("robot_id") else None
        if not robot:
            raise _error(422, "请选择业务数据库中的小车")
        map_id = payload.get("map_id")
        if map_id and db.get(MapModel, map_id) is None:
            raise _error(422, "业务地图不存在")
        item = model(id=task_id, name=str(payload.get("name") or ("文件运输" if kind == "delivery" else "多点巡航"))[:128],
                     robot_id=robot.id, map_id=map_id, created_by=user.id)
        if kind == "delivery":
            item.cargo = item.cargo_name = "文件"
            item.origin = item.start_location = "当前装件点"
            points = payload.get("waypoints")
            if isinstance(points, list) and points and isinstance(points[0], dict):
                item.destination = item.end_location = str(points[0].get("name") or "自选位置")[:255]
        db.add(item)
        db.flush()
    previous = execution(item)
    if not item.robot_id:
        raise _error(422, "此任务尚未分配小车，请先修改任务")
    if previous and previous["run_id"] != run_id:
        raise _error(409, "该业务任务已绑定执行记录，请新建任务")
    wire_payload = {**payload, "task_id": task_id}
    try:
        fingerprint = hashlib.sha256(json.dumps(wire_payload, sort_keys=True, allow_nan=False).encode()).hexdigest()
    except (ValueError, TypeError) as exc:
        raise _error(422, "执行请求包含无效参数") from exc
    if previous and previous.get("request_fingerprint") not in {None, fingerprint}:
        raise _error(409, "原请求已保存，不能在重试时更换坐标；请新建任务")
    if not previous:
        if item.status not in {"queued", "pending"}:
            raise _error(409, "此业务任务当前不能派发")
        store_execution(db, item, {"run_id": run_id, "task_id": task_id, "kind": kind, "state": "unconfirmed",
                               "message": "执行请求已保存，等待车端确认", "request": wire_payload, "request_fingerprint": fingerprint})
        record_audit(db, user, "navigation.prepare", "task", task_id)
        db.commit()
    result = await _call(db, "task", wire_payload)
    if result.get("run_id") != run_id or result.get("task_id") != task_id:
        raise _error(502, "车端任务标识不一致，尚未确认派发")
    store_execution(db, item, result)
    db.commit()
    return execution(item)


@router.get("/{kind}/{task_id}")
async def get_execution(kind: str, task_id: str, db: Session = Depends(get_db),
                        user: User = Depends(require_permission("robots.read"))):
    _permission(user, kind, False)
    item = _task(db, kind, task_id)
    previous = execution(item)
    if not previous:
        return {"state": "idle", "message": "此任务尚未配置地图目标"}
    result = await _call(db, "task", query={"run_id": previous["run_id"]})
    if result.get("run_id") != previous["run_id"] or result.get("task_id") != item.id:
        raise _error(502, "车端执行记录不匹配")
    store_execution(db, item, result)
    db.commit()
    return execution(item)


@router.post("/{kind}/{task_id}/action")
async def execution_action(kind: str, task_id: str, payload: dict = Body(...), db: Session = Depends(get_db),
                           user: User = Depends(require_permission("robots.read"))):
    _permission(user, kind)
    item = _task(db, kind, task_id)
    previous = execution(item)
    if not previous or payload.get("run_id") != previous["run_id"]:
        raise _error(409, "执行任务已变化，请刷新")
    if payload.get("action") == "retry" and previous["state"] == "unconfirmed" and previous.get("request"):
        result = await _call(db, "task", previous["request"])
    else:
        result = await _call(db, "task/action", {"run_id": previous["run_id"], "task_id": task_id, "kind": kind, "action": payload.get("action")})
    if result.get("task_id") != task_id or result.get("run_id") != previous["run_id"]:
        raise _error(502, "车端执行记录不匹配")
    store_execution(db, item, result)
    record_audit(db, user, "navigation." + str(payload.get("action")), "task", task_id, after=result)
    db.commit()
    return execution(item)
