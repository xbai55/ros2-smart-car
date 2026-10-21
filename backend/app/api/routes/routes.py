import json
from datetime import datetime, timezone
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from ...core.pagination import run_list
from ...models import MapModel, Route, User
from ...schemas.ops import RouteIn
from ...services.ops import json_loads, record_audit
from ..deps import get_db, require_permission

router = APIRouter(prefix="/routes", tags=["routes"])


def serialize_route(item: Route) -> dict:
    return {
        "id": item.id,
        "name": item.name,
        "map_id": item.map_id,
        "status": item.status,
        "points": json_loads(item.points, []),
        "start_point": json_loads(item.start_point, {}),
        "end_point": json_loads(item.end_point, {}),
        "waypoints": json_loads(item.waypoints, []),
        "path": json_loads(item.path, []),
        "parameters": json_loads(item.parameters, {}),
        "created_by": item.created_by,
        "created_at": item.created_at.isoformat() if item.created_at else None,
        "updated_at": item.updated_at.isoformat() if item.updated_at else None,
    }


def _check_map(db: Session, map_id: str | None) -> None:
    if map_id and db.get(MapModel, map_id) is None:
        raise HTTPException(status_code=400, detail={"code": "BAD_REQUEST", "message": "地图不存在"})


def _apply_payload(item: Route, payload: RouteIn) -> None:
    data = payload.model_dump()
    item.name = data["name"]
    item.map_id = data["map_id"]
    item.status = data["status"]
    item.points = json.dumps(data["points"] or [], ensure_ascii=False)
    item.start_point = json.dumps(data["start_point"] or {}, ensure_ascii=False)
    item.end_point = json.dumps(data["end_point"] or {}, ensure_ascii=False)
    item.waypoints = json.dumps(data["waypoints"] or [], ensure_ascii=False)
    item.path = json.dumps(data["path"] or [], ensure_ascii=False)
    item.parameters = json.dumps(data["parameters"] or {}, ensure_ascii=False)


@router.get("")
def list_routes(
    db: Session = Depends(get_db),
    _: User = Depends(require_permission("routes.read")),
    map_id: str | None = Query(default=None),
    status: str | None = Query(default=None),
    keyword: str | None = Query(default=None),
    page: int | None = Query(default=None, ge=1),
    page_size: int | None = Query(default=None, ge=1, le=200),
):
    stmt = select(Route).order_by(Route.name)
    if map_id:
        stmt = stmt.where(Route.map_id == map_id)
    if status:
        stmt = stmt.where(Route.status == status)
    if keyword:
        stmt = stmt.where(or_(Route.name.like(f"%{keyword}%")))
    return run_list(db, stmt, serialize_route, page, page_size)


@router.post("", status_code=201)
def create_route(
    payload: RouteIn,
    db: Session = Depends(get_db),
    user: User = Depends(require_permission("routes.manage")),
) -> dict:
    _check_map(db, payload.map_id)
    item = Route(id=str(uuid4()), created_by=user.id)
    _apply_payload(item, payload)
    db.add(item)
    db.flush()
    record_audit(db, user, "routes.create", "route", item.id, after=serialize_route(item))
    db.commit()
    return serialize_route(item)


@router.get("/{route_id}")
def get_route(
    route_id: str,
    db: Session = Depends(get_db),
    _: User = Depends(require_permission("routes.read")),
) -> dict:
    item = db.get(Route, route_id)
    if item is None:
        raise HTTPException(status_code=404, detail={"code": "NOT_FOUND", "message": "路线不存在"})
    return serialize_route(item)


@router.put("/{route_id}")
def update_route(
    route_id: str,
    payload: RouteIn,
    db: Session = Depends(get_db),
    user: User = Depends(require_permission("routes.manage")),
) -> dict:
    item = db.get(Route, route_id)
    if item is None:
        raise HTTPException(status_code=404, detail={"code": "NOT_FOUND", "message": "路线不存在"})
    _check_map(db, payload.map_id)
    before = serialize_route(item)
    _apply_payload(item, payload)
    item.updated_at = datetime.now(timezone.utc)
    db.flush()
    record_audit(
        db, user, "routes.update", "route", item.id, before=before, after=serialize_route(item)
    )
    db.commit()
    return serialize_route(item)
