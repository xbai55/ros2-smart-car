"""Authenticated queries over the separate diagnostics index."""
import io
import json
import sqlite3
import time
from contextlib import closing
from datetime import datetime, timedelta, timezone
from hashlib import sha256
from threading import BoundedSemaphore
from zipfile import ZIP_DEFLATED, ZipFile

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from ...core.config import settings
from ...models import AssistantEvent, AssistantExecution, AssistantPlan, MissionTask, PatrolTask, User
from ...services import diagnostics as diag
from ...services.ops import record_audit
from ..deps import get_current_user, get_db, require_permission

router = APIRouter(prefix="/diagnostics", tags=["diagnostics"])
read = require_permission("diagnostics.read")
export = require_permission("diagnostics.export")
from ...services.diagnostics.query import (query, project, visibility, technical, timeframe, page, unavailable, last_exports, last_reports, downloads)

@router.get("/events")
def events(request: Request, start: datetime | None = None, end: datetime | None = None,
           limit: int = Query(50, ge=1, le=200), cursor: str | None = Query(None, max_length=128),
           after: str | None = Query(None, max_length=128), user: User = Depends(read)):
    return query(lambda db: page(db, user, request, start, end, limit, cursor, after))


@router.get("/events/{event_id}")
def detail(event_id: str, user: User = Depends(read)):
    where = " AND ".join(["event_id=?", *visibility(user)])
    row = query(lambda db: db.execute(f"SELECT body FROM events WHERE {where}", (event_id,)).fetchone())
    if not row:
        raise HTTPException(404, "事件不存在")
    return project(row, technical(user))


@router.get("/traces/{trace_id}")
def trace(trace_id: str, request: Request, start: datetime | None = None, end: datetime | None = None,
          limit: int = Query(100, ge=1, le=200), cursor: str | None = Query(None, max_length=128),
          user: User = Depends(read)):
    if not diag.identifier(trace_id):
        raise HTTPException(404, "链路不存在")
    result = query(lambda db: page(db, user, request, start, end, limit, cursor, None,
                                   fixed_trace=trace_id))
    if not result.get('items') and not result.get('reset') and not cursor:
        raise HTTPException(404, '链路不存在')
    return result


@router.get("/stops")
def stops(request: Request, start: datetime | None = None, end: datetime | None = None,
          limit: int = Query(50, ge=1, le=200), cursor: str | None = Query(None, max_length=128),
          after: str | None = Query(None, max_length=128), user: User = Depends(read)):
    return query(lambda db: page(db, user, request, start, end, limit, cursor, after,
                                 ("(event_type LIKE 'motion.%' OR event_type LIKE 'stop.%')",)))


@router.get("/executions/{execution_id}")
def execution(execution_id: str, after: int = Query(0, ge=0), db: Session = Depends(get_db),
              user: User = Depends(require_permission("assistant.read"))):
    row = db.get(AssistantExecution, execution_id)
    if row is None or row.user_id != user.id or 'robots.read' not in user.permissions:
        raise HTTPException(404, "执行不存在")
    plan = db.get(AssistantPlan, row.plan_id)
    trace_id = getattr(plan, "trace_id", None)
    events = query(lambda index: index.execute(
        "SELECT seq,body FROM events WHERE seq>? AND (execution_id=? OR trace_id=?) ORDER BY seq LIMIT 101",
        (after, row.id, trace_id)).fetchall())
    business = db.scalars(select(AssistantEvent).where(
        AssistantEvent.execution_id == row.id, AssistantEvent.user_id == user.id
    ).order_by(AssistantEvent.id.desc()).limit(100)).all()
    return {"trace_id": trace_id, "state": row.state, "items": [project(event) for event in events[:100]],
            "next_after": events[99]["seq"] if len(events) > 100 else None,
            "business_events": [{"kind": e.kind, "id": e.id, "occurred_at": e.created_at} for e in business]}


@router.get("/health")
def health(user: User = Depends(read)):
    if diag.store is None:
        return {"status": "disabled"}
    data = diag.store.status()
    return data if technical(user) else {key: data.get(key) for key in ("status", "last_write", "vehicle")}


class ExportInput(BaseModel):
    start: datetime
    end: datetime
    format: str = "zip"
    robot_id: str | None = None


def rate_limit(bucket, user, seconds):
    now = time.monotonic()
    if now < bucket.get(user.id, 0):
        raise HTTPException(429, "请求过于频繁")
    if len(bucket) >= 1024:
        for key in [key for key, expiry in bucket.items() if expiry <= now]:
            bucket.pop(key, None)
        if len(bucket) >= 1024:
            raise HTTPException(429, "请求过于频繁")
    bucket[user.id] = now + seconds


@router.post("/exports")
def exports(payload: ExportInput, db: Session = Depends(get_db), user: User = Depends(export)):
    if "diagnostics.read" not in user.permissions:
        raise HTTPException(403, "缺少诊断读取权限")
    start, end = timeframe(payload.start, payload.end, max_days=1)
    if payload.format not in {"zip", "ndjson"} or (payload.robot_id and not diag.identifier(payload.robot_id)):
        raise HTTPException(422, "导出条件无效")
    rate_limit(last_exports, user, 10)
    if not downloads.acquire(blocking=False):
        raise HTTPException(429, "已有诊断包生成中")
    try:
        where = ["occurred_at>=?", "occurred_at<?", *visibility(user)]
        args = [start, end]
        if payload.robot_id:
            where.append("robot_id=?")
            args.append(payload.robot_id)
        raw = io.BytesIO()
        truncated = False
        sources = set()
        tasks, executions = set(), set()
        watermark = query(lambda index: index.execute('SELECT coalesce(max(seq),0) FROM events').fetchone()[0])
        where.append('seq <= ?')
        args.append(watermark)
        last = ('', '')
        for _ in range(50):
            rows = query(lambda index: index.execute(
                f"SELECT body,occurred_at,event_id FROM events WHERE {' AND '.join(where)} "
                'AND (occurred_at,event_id) > (?,?) ORDER BY occurred_at,event_id LIMIT 100',
                (*args, *last)).fetchall())
            if rows:
                last = (rows[-1]['occurred_at'], rows[-1]['event_id'])
            for row in rows:
                item = project(row, technical(user))
                line = (json.dumps(item, ensure_ascii=False) + "\n").encode()
                if raw.tell() + len(line) > 7 * 1024**2:
                    truncated = True
                    break
                raw.write(line)
                sources.add(item["source"])
                if item.get('task_id') and len(tasks) < 64:
                    tasks.add(item['task_id'])
                if item.get('execution_id') and len(executions) < 64:
                    executions.add(item['execution_id'])
            if truncated or len(rows) < 100:
                break
        else:
            truncated = True
        content = raw.getvalue()
        suffix, mime = "ndjson", "application/x-ndjson"
        if payload.format == "zip":
            bundle = io.BytesIO()
            status = diag.store.status()
            manifest = {"version": settings.app_version, "start": start, "end": end,
                        "truncated": truncated, "sources": sorted(sources),
                        "missing": sorted({"host", "jetson", "desktop", "frontend"} - sources),
                        "vehicle_sync": status.get("vehicle"), "store_status": status["status"]}
            task_records = []
            for model, permission, kind in ((PatrolTask, 'patrol.read', 'patrol'),
                                             (MissionTask, 'missions.read', 'delivery')):
                if permission in user.permissions and tasks:
                    for task in db.scalars(select(model).where(model.id.in_(tasks))):
                        task_records.append({'task_id': task.id, 'robot_id': task.robot_id,
                                             'kind': kind, 'state': task.status})
            business_events = []
            if executions and 'assistant.read' in user.permissions:
                stmt = select(AssistantEvent).where(
                    AssistantEvent.user_id == user.id, AssistantEvent.execution_id.in_(executions),
                    AssistantEvent.created_at >= payload.start.astimezone(timezone.utc),
                    AssistantEvent.created_at < payload.end.astimezone(timezone.utc),
                ).order_by(AssistantEvent.created_at.desc()).limit(200)
                business_events = [{'event_id': item.id, 'execution_id': item.execution_id, 'kind': item.kind,
                                    'occurred_at': item.created_at.isoformat()} for item in db.scalars(stmt)]
            if not task_records:
                manifest['missing'].append('task_metadata')
            if not business_events:
                manifest['missing'].append('authorized_assistant_events')
            with ZipFile(bundle, "w", ZIP_DEFLATED) as archive:
                archive.writestr("events.ndjson", content)
                archive.writestr('health.json', json.dumps(status if technical(user) else {
                    'status': status['status'], 'vehicle': status.get('vehicle'),
                }, ensure_ascii=False))
                archive.writestr('tasks.json', json.dumps(task_records, ensure_ascii=False))
                archive.writestr('assistant-events.json', json.dumps(business_events, ensure_ascii=False))
                archive.writestr("manifest.json", json.dumps(manifest, ensure_ascii=False))
            content, suffix, mime = bundle.getvalue(), "zip", "application/zip"
        record_audit(db, user, "diagnostics.export", "diagnostics", None,
                     after={"start": start, "end": end, "format": suffix, "truncated": truncated})
        db.commit()
        return Response(content, media_type=mime, headers={
            "Content-Disposition": f'attachment; filename="insightrover-diagnostics.{suffix}"',
            "X-Diagnostics-Truncated": str(truncated).lower(),
        })
    finally:
        downloads.release()


@router.post("/client-events", status_code=204)
async def client_event(request: Request, user: User = Depends(get_current_user)):
    rate_limit(last_reports, user, 30)
    body = bytearray()
    async for chunk in request.stream():
        if len(body) + len(chunk) > 256:
            raise HTTPException(413, "事件过大")
        body.extend(chunk)
    try:
        value = json.loads(body)
    except (ValueError, UnicodeError):
        raise HTTPException(422, "事件格式无效") from None
    if not isinstance(value, dict) or set(value) != {"reason"} or value["reason"] not in (
        "diagnostic_disconnected", "diagnostic_reconnected", "status_disconnected"
    ):
        raise HTTPException(422, "事件类型无效")
    diag.emit("client.connection", value["reason"], module="web_console", source="frontend")
    return Response(status_code=204)
