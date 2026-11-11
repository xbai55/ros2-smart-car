"""Shared bounded diagnostic queries and visibility policy for UI and agent."""
import json
import sqlite3
import time
from contextlib import closing
from datetime import datetime, timedelta, timezone
from hashlib import sha256
from threading import BoundedSemaphore
from fastapi import HTTPException
from .. import diagnostics as diag

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


