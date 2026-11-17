"""Shared persistence for vehicle-confirmed navigation execution."""
import json
from datetime import datetime, timezone
from fastapi import HTTPException
from sqlalchemy import update
from ..models import MissionTask
from .ops import json_loads


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
            # Immutable dispatch survives vehicle replies and is the only retry source.
            value = {**value, **{k:previous[k] for k in ('request','request_fingerprint') if k in previous}}
            if previous.get('sync_state') == 'cancel_pending' and value['state'] not in {'completed','cancelled','failed'} and value.get('sync_state') != 'cancel_pending':
                return False
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
