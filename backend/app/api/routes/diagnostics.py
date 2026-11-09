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
queries = BoundedSemaphore(4)
downloads = BoundedSemaphore(1)
last_exports = {}
last_reports = {}


def unavailable():
    return HTTPException(503, "诊断存储暂不可用")


def query(fn):
    if diag.store is None:
        raise unavailable()
    if not queries.acquire(blocking=False):
        raise HTTPException(429, "诊断查询繁忙")
    try:
        with closing(diag.store.connect(readonly=True)) as db:
            until = time.monotonic() + .25
            db.set_progress_handler(lambda: int(time.monotonic() > until), 1000)
            return fn(db)
    except (OSError, sqlite3.Error):
        raise unavailable() from None
    finally:
        queries.release()


def technical(user):
    return "diagnostics.technical" in user.permissions


def visibility(user):
    constraints = []
    if "robots.read" not in user.permissions:
        constraints.append("robot_id IS NULL")
    if not {"patrol.read", "missions.read"} <= user.permissions:
        constraints.append("task_id IS NULL")
    if not technical(user):
        constraints.append("module != 'assistant_private'")
        constraints.append("(execution_id IS NULL AND event_type NOT LIKE 'assistant.%')")
    return constraints


def project(row, privileged=False):
    value = json.loads(row["body"])
    if not privileged:
        value.pop("exception", None)
        for key in ("controller_id", "control_epoch", "provider", "model"):
            value["context"].pop(key, None)
    return value


def timeframe(start, end, *, max_days=14, default_days=1):
    if (start and start.tzinfo is None) or (end and end.tzinfo is None):
        raise HTTPException(422, "时间必须包含时区")
    end = end or datetime.now(timezone.utc)
    start = start or end - timedelta(days=default_days)
    if not timedelta(0) < end - start <= timedelta(days=max_days):
        raise HTTPException(422, "时间范围无效或超过限制")
    return diag.utc(start.timestamp()), diag.utc(end.timestamp())


def page(db, user, request, start, end, limit, cursor, after, extra=(), fixed_trace=None):
    if cursor and after:
        raise HTTPException(422, "只能使用一种游标")
    where = [*visibility(user), *extra, "occurred_at >= ?"]
    start_at, end_at = timeframe(start, end, default_days=14 if fixed_trace else 1)
    args = [start_at]
    if end is not None:
        where.append("occurred_at < ?")
        args.append(end_at)
    for field in diag.FIELDS:
        value = fixed_trace if field == 'trace_id' and fixed_trace else request.query_params.get(field)
        if value is not None:
            if not diag.identifier(value):
                raise HTTPException(422, "筛选值无效")
            where.append(f"{field} = ?")
            args.append(value)
    term = request.query_params.get("q")
    if term:
        if len(term) > 96:
            raise HTTPException(422, "关键词过长")
        where.append("(instr(message, ?) OR instr(reason_code, ?))")
        args.extend((term, term))
    meta = dict(db.execute("SELECT key,value FROM metadata").fetchall())
    high = db.execute("SELECT coalesce((SELECT seq FROM sqlite_sequence WHERE name='events'),0)").fetchone()[0]
    pruned = int(meta.get("pruned", "0"))
    key = sha256(json.dumps([where, args[1:] if start is None else args, user.id], ensure_ascii=False).encode()).hexdigest()[:16]
    base = f"{meta['generation']}.{key}"
    marker = after or cursor
    if marker:
        parts = marker.split(".")
        if len(parts) != (3 if after else 4) or ".".join(parts[:2]) != base:
            return {"items": [], "reset": True}
        try:
            water = int(parts[2])
            previous = None if after else int(parts[3])
        except ValueError:
            raise HTTPException(422, "游标无效") from None
        if not 0 <= water <= high or water < pruned:
            return {"items": [], "reset": True}
    else:
        water = high
    if after:
        where.append("seq > ?")
        args.append(water)
        order = "seq"
    else:
        where.append("seq <= ?")
        args.append(water)
        if cursor:
            anchor = db.execute("SELECT occurred_at,event_id FROM events WHERE seq=?", (previous,)).fetchone()
            if not anchor:
                return {"items": [], "reset": True}
            where.append("(occurred_at,event_id) < (?,?)")
            args.extend(anchor)
        order = "occurred_at DESC,event_id DESC"
    rows = db.execute(f"SELECT seq,body FROM events WHERE {' AND '.join(where)} ORDER BY {order} LIMIT ?",
                      (*args, limit + 1)).fetchall()
    more = len(rows) > limit
    rows = rows[:limit]
    return {
        "items": [project(row, technical(user)) for row in rows],
        "next_cursor": f"{base}.{water}.{rows[-1]['seq']}" if more and not after else None,
        "after": f"{base}.{rows[-1]['seq'] if after and more else high if after else water}",
        "has_more": more,
    }


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
