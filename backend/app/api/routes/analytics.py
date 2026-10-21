"""数据统计：全部基于数据库中的业务数据聚合，不使用固定假数据。"""
from collections import Counter
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ...models import Incident, MissionTask, PatrolTask, Robot, User
from ...services.realtime import get_realtime_store
from ...services.robots import serialize_robot
from ..deps import get_db, require_permission

router = APIRouter(prefix="/analytics", tags=["analytics"])
# 项目文档中使用 /statistics/*，这里提供同一套实现的别名
statistics_router = APIRouter(prefix="/statistics", tags=["statistics"])


def _rate(part: int, total: int) -> float:
    return round(part / total * 100, 1) if total else 0.0


def _count_by(db: Session, column) -> dict[str, int]:
    rows = db.execute(select(column, func.count()).group_by(column)).all()
    return {str(key): int(count) for key, count in rows}


def _robot_statuses(db: Session) -> tuple[Counter, dict[str, dict]]:
    store = get_realtime_store()
    realtime = store.all_statuses()
    robots = db.execute(select(Robot)).scalars().all()
    payloads = {r.id: serialize_robot(r, realtime.get(r.id)) for r in robots}
    fresh = {key: value for key, value in payloads.items() if value["source"] == "realtime"}
    return Counter(value["status"] for value in payloads.values()), fresh


def _task_trend(db: Session, days: int = 7) -> list[dict]:
    start = datetime.now(timezone.utc) - timedelta(days=days - 1)
    buckets: dict[str, dict[str, int]] = {}
    for offset in range(days):
        key = (start + timedelta(days=offset)).date().isoformat()
        buckets[key] = {"date": key, "patrol": 0, "mission": 0, "total": 0}

    for model, label in ((PatrolTask, "patrol"), (MissionTask, "mission")):
        created = db.execute(select(model.created_at)).scalars().all()
        for value in created:
            if value is None:
                continue
            if value.tzinfo is None:
                value = value.replace(tzinfo=timezone.utc)
            key = value.date().isoformat()
            if key in buckets:
                buckets[key][label] += 1
                buckets[key]["total"] += 1
    return list(buckets.values())


def _overview(db: Session) -> dict:
    patrols = db.execute(select(PatrolTask)).scalars().all()
    missions = db.execute(select(MissionTask)).scalars().all()
    incidents = db.execute(select(Incident)).scalars().all()
    statuses, _ = _robot_statuses(db)

    patrol_completed = sum(1 for p in patrols if p.status == "completed")
    patrol_failed = sum(1 for p in patrols if p.status == "failed")
    mission_completed = sum(1 for m in missions if m.status == "completed")
    mission_failed = sum(1 for m in missions if m.status == "failed")
    incident_resolved = sum(1 for i in incidents if i.status == "resolved")
    robot_total = sum(statuses.values())

    return {
        "patrol": {
            "total": len(patrols),
            "completed": patrol_completed,
            "failed": patrol_failed,
            "completion_rate": _rate(patrol_completed, len(patrols)),
            "by_status": dict(Counter(p.status for p in patrols)),
        },
        "mission": {
            "total": len(missions),
            "completed": mission_completed,
            "failed": mission_failed,
            "completion_rate": _rate(mission_completed, len(missions)),
            "by_status": dict(Counter(m.status for m in missions)),
        },
        "incident": {
            "total": len(incidents),
            "resolved": incident_resolved,
            "unresolved": len(incidents) - incident_resolved,
            "resolution_rate": _rate(incident_resolved, len(incidents)),
            "by_severity": dict(Counter(i.severity for i in incidents)),
            "by_type": dict(Counter(i.type for i in incidents)),
            "by_status": dict(Counter(i.status for i in incidents)),
        },
        "robot": {
            "total": robot_total,
            "online": statuses.get("online", 0),
            "offline": statuses.get("offline", 0),
            "degraded": statuses.get("degraded", 0),
            "estop": statuses.get("estop", 0),
            "online_rate": _rate(statuses.get("online", 0), robot_total),
            "by_status": dict(statuses),
        },
    }


@router.get("/summary")
def analytics_summary(
    db: Session = Depends(get_db),
    _: User = Depends(require_permission("analytics.read")),
) -> dict:
    return _overview(db)


@router.get("/overview")
def analytics_overview(
    db: Session = Depends(get_db),
    _: User = Depends(require_permission("analytics.read")),
) -> dict:
    """任务总数、完成任务数、失败任务数、任务完成率、异常事件数、设备在线率。"""
    overview = _overview(db)
    total = overview["patrol"]["total"] + overview["mission"]["total"]
    completed = overview["patrol"]["completed"] + overview["mission"]["completed"]
    failed = overview["patrol"]["failed"] + overview["mission"]["failed"]
    return {
        "tasks": {
            "total": total,
            "completed": completed,
            "failed": failed,
            "completion_rate": _rate(completed, total),
        },
        **overview,
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }


@router.get("/tasks")
def analytics_tasks(
    db: Session = Depends(get_db),
    _: User = Depends(require_permission("analytics.read")),
    days: int = Query(default=7, ge=1, le=90),
) -> dict:
    patrol_by_status = _count_by(db, PatrolTask.status)
    mission_by_status = _count_by(db, MissionTask.status)
    patrol_total = sum(patrol_by_status.values())
    mission_total = sum(mission_by_status.values())
    patrol_completed = patrol_by_status.get("completed", 0)
    mission_completed = mission_by_status.get("completed", 0)
    return {
        "patrol": {
            "total": patrol_total,
            "completed": patrol_completed,
            "failed": patrol_by_status.get("failed", 0),
            "completion_rate": _rate(patrol_completed, patrol_total),
            "by_status": patrol_by_status,
        },
        "mission": {
            "total": mission_total,
            "completed": mission_completed,
            "failed": mission_by_status.get("failed", 0),
            "completion_rate": _rate(mission_completed, mission_total),
            "by_status": mission_by_status,
        },
        "trend": _task_trend(db, days),
    }


@router.get("/robots")
def analytics_robots(
    db: Session = Depends(get_db),
    _: User = Depends(require_permission("analytics.read")),
) -> dict:
    statuses, realtime = _robot_statuses(db)
    total = sum(statuses.values())
    return {
        "total": total,
        "online": statuses.get("online", 0),
        "online_rate": _rate(statuses.get("online", 0), total),
        "by_status": dict(statuses),
        "realtime": len(realtime),
        "source": "realtime" if realtime else "unavailable",
    }


@router.get("/incidents")
def analytics_incidents(
    db: Session = Depends(get_db),
    _: User = Depends(require_permission("analytics.read")),
) -> dict:
    incidents = db.execute(select(Incident)).scalars().all()
    resolved = sum(1 for i in incidents if i.status == "resolved")
    return {
        "total": len(incidents),
        "resolved": resolved,
        "resolution_rate": _rate(resolved, len(incidents)),
        "by_type": dict(Counter(i.type for i in incidents)),
        "by_severity": dict(Counter(i.severity for i in incidents)),
        "by_status": dict(Counter(i.status for i in incidents)),
    }


@statistics_router.get("/overview")
def statistics_overview(
    db: Session = Depends(get_db),
    _: User = Depends(require_permission("analytics.read")),
) -> dict:
    return analytics_overview(db=db, _=_)


@statistics_router.get("/incidents")
def statistics_incidents(
    db: Session = Depends(get_db),
    _: User = Depends(require_permission("analytics.read")),
) -> dict:
    return analytics_incidents(db=db, _=_)


@statistics_router.get("/robots/{robot_id}")
def statistics_robot(
    robot_id: str,
    db: Session = Depends(get_db),
    _: User = Depends(require_permission("analytics.read")),
) -> dict:
    robot = db.get(Robot, robot_id)
    if robot is None:
        raise HTTPException(status_code=404, detail={"code": "NOT_FOUND", "message": "机器人不存在"})
    patrols = db.execute(
        select(PatrolTask).where(PatrolTask.robot_id == robot_id)
    ).scalars().all()
    missions = db.execute(
        select(MissionTask).where(MissionTask.robot_id == robot_id)
    ).scalars().all()
    incidents = db.execute(select(Incident).where(Incident.robot_id == robot_id)).scalars().all()
    store = get_realtime_store()
    return {
        "robot_id": robot_id,
        "name": robot.name,
        "status": serialize_robot(robot, store.get_status(robot_id))["status"],
        "patrol_total": len(patrols),
        "patrol_completed": sum(1 for p in patrols if p.status == "completed"),
        "mission_total": len(missions),
        "mission_completed": sum(1 for m in missions if m.status == "completed"),
        "incident_total": len(incidents),
    }
