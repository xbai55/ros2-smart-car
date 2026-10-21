import json
from datetime import datetime, timezone
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from ...core.pagination import run_list
from ...models import Incident, Robot, User
from ...schemas.ops import IncidentAction, IncidentCreate, IncidentUpdate
from ...services.ops import json_loads, notify_users, record_audit
from ..deps import get_db, require_permission

router = APIRouter(prefix="/incidents", tags=["incidents"])

# 文档使用 open/processing/resolved/ignored，内部沿用 open/acknowledged/handling/resolved/dismissed
STATUS_ALIASES = {"processing": "handling", "ignored": "dismissed"}

_TRANSITIONS = {
    "confirm": {"open": "acknowledged"},
    "handle": {"open": "handling", "acknowledged": "handling"},
    "resolve": {"open": "resolved", "acknowledged": "resolved", "handling": "resolved"},
    "dismiss": {"open": "dismissed", "acknowledged": "dismissed", "handling": "dismissed"},
    "ignore": {"open": "dismissed", "acknowledged": "dismissed", "handling": "dismissed"},
}


def normalize_status(value: str) -> str:
    return STATUS_ALIASES.get(value, value)


def _parse_dt(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def serialize_incident(item: Incident) -> dict:
    return {
        "id": item.id,
        "type": item.type,
        "severity": item.severity,
        "status": item.status,
        "robot_id": item.robot_id,
        "task_id": item.task_id,
        "title": item.title,
        "description": item.description,
        "location": item.location,
        "media_keys": json_loads(item.media_keys),
        "evidence": json_loads(item.evidence, {}),
        "image_url": item.image_url,
        "video_url": item.video_url,
        "handled_by": item.handled_by,
        "handle_result": item.handle_result,
        "resolution_note": item.resolution_note,
        "occurred_at": item.occurred_at.isoformat() if item.occurred_at else None,
        "handled_at": item.handled_at.isoformat() if item.handled_at else None,
        "created_at": item.created_at.isoformat() if item.created_at else None,
        "resolved_at": item.resolved_at.isoformat() if item.resolved_at else None,
    }


def _get_incident(db: Session, incident_id: str) -> Incident:
    item = db.get(Incident, incident_id)
    if item is None:
        raise HTTPException(status_code=404, detail={"code": "NOT_FOUND", "message": "事件不存在"})
    return item


@router.get("")
def list_incidents(
    db: Session = Depends(get_db),
    _: User = Depends(require_permission("incidents.read")),
    severity: str | None = Query(default=None),
    status: str | None = Query(default=None),
    robot_id: str | None = Query(default=None),
    type: str | None = Query(default=None),
    keyword: str | None = Query(default=None),
    page: int | None = Query(default=None, ge=1),
    page_size: int | None = Query(default=None, ge=1, le=200),
):
    stmt = select(Incident).order_by(Incident.created_at.desc())
    if severity:
        stmt = stmt.where(Incident.severity == severity)
    if status:
        stmt = stmt.where(Incident.status == normalize_status(status))
    if robot_id:
        stmt = stmt.where(Incident.robot_id == robot_id)
    if type:
        stmt = stmt.where(Incident.type == type)
    if keyword:
        like = f"%{keyword}%"
        stmt = stmt.where(or_(Incident.title.like(like), Incident.description.like(like)))
    return run_list(db, stmt, serialize_incident, page, page_size)


@router.get('/safety/status')
async def safety_status(db: Session = Depends(get_db), _: User = Depends(require_permission('incidents.read'))):
    from ...services.safety_ingest import get_vehicle_url, pipeline_status
    from ...gateway.robot_gateway import RobotGateway
    url = get_vehicle_url(db)
    try:
        async with RobotGateway._client(3.) as client:
            response = await client.get(url + '/api/safety/status')
            response.raise_for_status()
            return {**response.json(), 'ingest': dict(pipeline_status)}
    except Exception:
        return {'state': 'unavailable', 'message': '暂未连接到车端巡检识别服务', 'detections': [], 'ingest': dict(pipeline_status)}


@router.get('/safety/corridors')
async def get_corridors(db: Session = Depends(get_db), _: User = Depends(require_permission('incidents.read'))):
    return await _corridor_request(db)


@router.post('/safety/corridors')
async def save_corridors(payload: dict, db: Session = Depends(get_db), user: User = Depends(require_permission('incidents.manage'))):
    result = await _corridor_request(db, payload)
    record_audit(db, user, 'safety.configure_corridors', 'robot', None, after=payload)
    db.commit()
    return result


async def _corridor_request(db, payload=None):
    from ...services.safety_ingest import get_vehicle_url
    from ...gateway.robot_gateway import RobotGateway
    import httpx
    try:
        async with RobotGateway._client(10.) as client:
            url = get_vehicle_url(db) + '/api/safety/corridors'
            response = await (client.get(url) if payload is None else client.post(url, json=payload))
            response.raise_for_status()
            return response.json()
    except httpx.HTTPStatusError as exc:
        raise HTTPException(exc.response.status_code, exc.response.json().get('detail', '通道配置失败')) from exc
    except httpx.HTTPError as exc:
        raise HTTPException(502, '车端通道配置未确认，请恢复连接后重试') from exc


@router.post("", status_code=201)
def create_incident(
    payload: IncidentCreate,
    db: Session = Depends(get_db),
    user: User = Depends(require_permission("incidents.manage")),
) -> dict:
    if payload.robot_id and db.get(Robot, payload.robot_id) is None:
        raise HTTPException(status_code=400, detail={"code": "BAD_REQUEST", "message": "机器人不存在"})
    data = payload.model_dump()
    data["media_keys"] = json.dumps(data.pop("media_keys", []), ensure_ascii=False)
    data["occurred_at"] = _parse_dt(data.pop("occurred_at", None)) or datetime.now(timezone.utc)
    item = Incident(id=str(uuid4()), **data)
    db.add(item)
    db.flush()
    record_audit(db, user, "incidents.create", "incident", item.id, after=serialize_incident(item))
    notify_users(db, kind="incident", title=item.title, body=item.description, ref_id=item.id)
    db.commit()
    return serialize_incident(item)


@router.get("/{incident_id}")
def get_incident(
    incident_id: str,
    db: Session = Depends(get_db),
    _: User = Depends(require_permission("incidents.read")),
) -> dict:
    return serialize_incident(_get_incident(db, incident_id))


@router.put("/{incident_id}")
def update_incident(
    incident_id: str,
    payload: IncidentUpdate,
    db: Session = Depends(get_db),
    user: User = Depends(require_permission("incidents.manage")),
) -> dict:
    item = _get_incident(db, incident_id)
    before = serialize_incident(item)
    data = payload.model_dump(exclude_unset=True)
    if "status" in data and data["status"]:
        item.status = normalize_status(data.pop("status"))
        item.handled_by = user.id
        if item.handled_at is None:
            item.handled_at = datetime.now(timezone.utc)
        if item.status == "resolved":
            item.resolved_at = datetime.now(timezone.utc)
    for key, value in data.items():
        setattr(item, key, value)
    db.flush()
    record_audit(
        db, user, "incidents.update", "incident", item.id, before=before, after=serialize_incident(item)
    )
    db.commit()
    return serialize_incident(item)


@router.post("/{incident_id}/actions")
def incident_action(
    incident_id: str,
    payload: IncidentAction,
    db: Session = Depends(get_db),
    user: User = Depends(require_permission("incidents.manage")),
) -> dict:
    item = _get_incident(db, incident_id)
    allowed = _TRANSITIONS[payload.action]
    if item.status not in allowed:
        raise HTTPException(
            status_code=409,
            detail={"code": "STATE_CONFLICT", "message": f"当前状态 {item.status} 不允许 {payload.action}"},
        )
    before = serialize_incident(item)
    now = datetime.now(timezone.utc)
    item.status = allowed[item.status]
    item.handled_by = user.id
    item.handled_at = item.handled_at or now
    if payload.action in ("resolve", "dismiss", "ignore"):
        item.resolution_note = payload.note
        item.handle_result = payload.note or item.handle_result
    if payload.action == "resolve":
        item.resolved_at = now
    record_audit(
        db, user, f"incidents.{payload.action}", "incident", item.id, before=before, after=serialize_incident(item)
    )
    notify_users(db, kind="incident", title=f"事件{payload.action}", body=item.title, ref_id=item.id)
    db.commit()
    return serialize_incident(item)
