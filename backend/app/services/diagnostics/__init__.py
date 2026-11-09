"""Bounded diagnostic index independent of the business database."""
import json
import math
import os
import re
import sqlite3
import time
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path
from queue import Empty, Full, Queue
from threading import Event, Lock, Thread
from uuid import uuid4

from ...core.diagnostic_context import context

LEVELS = ("DEBUG", "INFO", "WARN", "ERROR", "CRITICAL")
IDS = ("request_id", "trace_id", "span_id", "robot_id", "task_id", "execution_id",
       "run_id", "episode_id", "host_id", "node")
IDENT = re.compile(r"[A-Za-z0-9_.:-]{1,96}\Z")
SECRET = re.compile(r'(?:^eyJ|^sk[-_]|^gh[pousr]_|^github_pat_|bearer|password|api_key)', re.I)
FIELDS = ("level", "source", "service", "module", "robot_id", "task_id",
          "execution_id", "run_id", "trace_id", "episode_id", "event_type")
DETAIL = {
    "status_code", "elapsed_ms", "controller_confirmed", "stationary_confirmed",
    "request_sent", "odom_age", "linear_speed", "angular_speed", "previous_mode",
    "mode", "requested", "previous_output", "winner_module", "policy", "final", "winner", "first", "gates",
    "lease_blocked", "lease_purpose", "lease_reason", "forward_limit", "command",
    "state", "version", "step_index", "distance_m", "plan_id", "prompt_tokens",
    "completion_tokens", "total_tokens", "provider", "model", "tool", "operation",
    "target", "exit_code", "failures", "controller_id", "control_epoch",
}
CODES = {
    "http.completed": "HTTP 请求结束",
    "http.failed": "HTTP 请求处理失败",
    "host.started": "主机服务启动",
    "host.stopping": "主机服务正在退出",
    "gateway.response": "收到车端响应",
    'gateway.connected': '车端遥测已恢复',
    'socket.closed': '实时连接结束',
    "gateway.failed": "车端通信失败",
    "gateway.stop": "主机收到停车结果",
    "motion.zero": "控制器已发布零速度",
    "motion.blocked": "运动意图受到阻断",
    "motion.stationary": "停车后里程计确认静止",
    "motion.unconfirmed": "停车后未确认静止",
    "motion.rejected": "控制器拒绝运动请求",
    "stop.requested": "车端收到停止请求",
    "stop.result": "独立停车流程返回结果",
    "lease.changed": "控制权状态变化",
    "node.started": "ROS 节点启动",
    "node.exited": "ROS 节点退出",
    "task.changed": "任务状态变化",
    "assistant.model": "助手模型调用结束",
    "assistant.tool": "助手工具调用结束",
    "assistant.plan": "助手已生成草案",
    "assistant.confirm": "助手计划确认结果",
    "assistant.execution": "助手执行状态变化",
    "assistant.dispatch": "助手派发任务",
    "client.connection": "控制台通信异常",
    "desktop.started": "桌面后台启动",
    "desktop.exited": "桌面后台退出",
}


def utc(timestamp=None):
    return datetime.fromtimestamp(timestamp if timestamp is not None else time.time(),
                                  timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def identifier(value):
    return value if isinstance(value, str) and IDENT.fullmatch(value) and not SECRET.search(value) else None


def safe_detail(value):
    if type(value) is bool or value is None:
        return value
    if type(value) in (float, int):
        return value if abs(value) <= 1e14 and math.isfinite(value) else None
    if isinstance(value, (tuple, list)):
        return [safe_detail(v) for v in value[:8] if not isinstance(v, (dict, tuple, list))]
    return identifier(value)


def normalize(raw):
    if raw.get('schema_version', 1) != 1:
        raise ValueError('unsupported diagnostic schema')
    kind = raw.get("event_type")
    if not isinstance(kind, str) or kind not in CODES:
        raise ValueError("unknown diagnostic event")
    source = raw.get("source")
    if source not in ("host", "jetson", "desktop", "frontend"):
        raise ValueError("unknown source")
    if not identifier(raw.get("event_id")):
        raise ValueError("invalid event id")
    stamp = raw.get("occurred_at")
    if not isinstance(stamp, str) or len(stamp) > 36:
        raise ValueError("invalid timestamp")
    occurred = datetime.fromisoformat(stamp.replace("Z", "+00:00"))
    if occurred.tzinfo is None:
        raise ValueError("timestamp must include timezone")
    details = raw.get("context")
    details = details if isinstance(details, dict) else {}
    event = {
        "schema_version": 1, "event_id": raw["event_id"],
        "occurred_at": utc(occurred.timestamp()), "observed_at": utc(),
        "event_type": kind, "reason_code": identifier(raw.get("reason_code")) or "unknown",
        "message": CODES[kind], "level": raw.get("level") if raw.get("level") in LEVELS else "INFO",
        "source": source, "service": identifier(raw.get("service")) or source,
        "module": identifier(raw.get("module")) or "unknown",
        "context": {key: safe_detail(details[key]) for key in DETAIL & details.keys()},
        "critical": kind.startswith(("motion.", "stop.")) or raw.get("level") in LEVELS[3:],
    }
    event.update({key: identifier(raw[key]) for key in IDS if key in raw})
    if source == "host" and isinstance(raw.get("exception"), dict):
        err = raw["exception"]
        event["exception"] = {"type": identifier(err.get("type")),
                              "frames": safe_detail(err.get("frames"))}
    if len(json.dumps(event, ensure_ascii=False).encode()) > 4096:
        raise ValueError("oversized diagnostic event")
    return event


class DiagnosticStore:
    def __init__(self, path, *, max_mib=48, normal_days=7, critical_days=14):
        self.path = Path(path)
        self.max_mib = max(4, min(48, max_mib))
        self.days = (max(1, min(14, normal_days)), max(1, min(14, critical_days)))
        self.host_id = uuid4().hex
        self.queues = (Queue(1024), Queue(256))
        self.halt = Event()
        self.write_lock = Lock()
        self.thread = None
        self.health = {"status": "starting", "dropped": 0, "invalid": 0, "last_write": None}

    def connect(self, *, readonly=False):
        target = self.path.resolve().as_uri() + '?mode=ro' if readonly else self.path
        db = sqlite3.connect(target, timeout=.2, uri=readonly)
        db.row_factory = sqlite3.Row
        return db

    def init(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with closing(self.connect()) as db, db:
            db.executescript("""
            PRAGMA journal_mode=DELETE;
            PRAGMA temp_store=MEMORY;
            CREATE TABLE IF NOT EXISTS metadata (key TEXT PRIMARY KEY, value TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS events (
                seq INTEGER PRIMARY KEY AUTOINCREMENT, event_id TEXT UNIQUE NOT NULL,
                occurred_at TEXT NOT NULL, observed_at TEXT NOT NULL, critical INTEGER NOT NULL,
                level TEXT, source TEXT, service TEXT, module TEXT, robot_id TEXT, task_id TEXT,
                execution_id TEXT, run_id TEXT, trace_id TEXT, episode_id TEXT, event_type TEXT,
                message TEXT NOT NULL, reason_code TEXT NOT NULL, body TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS event_time ON events(occurred_at, event_id);
            CREATE INDEX IF NOT EXISTS event_retention ON events(critical, observed_at);
            """)
            for field in FIELDS:
                db.execute(f"CREATE INDEX IF NOT EXISTS event_{field} ON events({field}, occurred_at)")
            db.execute("INSERT OR IGNORE INTO metadata VALUES ('generation', ?)", (uuid4().hex,))
            db.execute("INSERT OR IGNORE INTO metadata VALUES ('pruned', '0')")

    def offer(self, raw):
        lane = int(raw.get("event_type", "").startswith(("motion.", "stop."))
                   or raw.get("level") in LEVELS[3:])
        try:
            self.queues[lane].put_nowait(raw)
        except Full:
            self.health["dropped"] += 1

    def write(self, rows, checkpoint=None):
        batch = []
        for raw in rows:
            try:
                batch.append(normalize(raw))
            except (TypeError, ValueError, OverflowError, OSError):
                self.health["invalid"] += 1
        with self.write_lock, closing(self.connect()) as db, db:
            page = db.execute("PRAGMA page_size").fetchone()[0]
            db.execute(f"PRAGMA max_page_count={self.max_mib * 1024 * 1024 // page}")
            for critical, days in enumerate(self.days):
                self.prune(db, "critical=? AND observed_at<?", (critical, utc(time.time()-days*86400)))
            used = db.execute("PRAGMA page_count").fetchone()[0] - db.execute("PRAGMA freelist_count").fetchone()[0]
            if used * page > self.max_mib * 1024 * 1024 * .65:
                self.prune(db, "critical=0", ())
            if used * page > self.max_mib * 1024 * 1024 * .90:
                self.prune(db, "critical=1", ())
            for item in batch:
                if item['source'] == 'jetson' and item.get('run_id') and item.get('robot_id'):
                    links = db.execute(
                        'SELECT DISTINCT task_id FROM events WHERE run_id=? AND robot_id=? '
                        'AND source=? AND task_id IS NOT NULL LIMIT 2',
                        (item['run_id'], item['robot_id'], 'host'),
                    ).fetchall()
                    if len(links) == 1:
                        item['task_id'] = links[0][0]
            keys = ("event_id", "occurred_at", "observed_at", "critical", *FIELDS, "message", "reason_code")
            db.executemany(f"INSERT OR IGNORE INTO events ({','.join(keys)},body) "
                           f"VALUES ({','.join('?' for _ in range(len(keys)+1))})", [
                               (*[item.get(key) for key in keys], json.dumps(item, ensure_ascii=False))
                               for item in batch])
            if checkpoint:
                records = [checkpoint] if isinstance(checkpoint, tuple) else checkpoint
                db.executemany('INSERT OR REPLACE INTO metadata VALUES (?,?)', records)
        self.health.update(status="ready", last_write=utc())

    @staticmethod
    def prune(db, where, values):
        selected = db.execute(
            f"SELECT seq FROM events WHERE {where} ORDER BY observed_at LIMIT 256", values
        ).fetchall()
        if selected:
            db.executemany("DELETE FROM events WHERE seq=?", selected)
            db.execute("UPDATE metadata SET value=max(CAST(value AS INTEGER), ?) WHERE key='pruned'",
                       (max(row[0] for row in selected),))

    def run(self):
        initialized = False
        maintenance = 0
        while not self.halt.is_set() or any(not queue.empty() for queue in self.queues):
            try:
                if not initialized:
                    self.init()
                    initialized = True
                batch = []
                for queue, limit in ((self.queues[1], 48), (self.queues[0], 64)):
                    while len(batch) < limit:
                        try:
                            batch.append(queue.get_nowait())
                        except Empty:
                            break
                if batch or time.monotonic() >= maintenance:
                    try:
                        self.write(batch)
                    except (sqlite3.Error, OSError):
                        self.health["dropped"] += len(batch)
                        raise
                    maintenance = time.monotonic() + 30
            except (OSError, sqlite3.Error):
                self.health["status"] = "storage_unavailable"
                if self.halt.wait(1):
                    return
            self.halt.wait(.25)

    def start(self):
        self.halt.clear()
        self.thread = Thread(target=self.run, name="diagnostic-writer", daemon=True)
        self.thread.start()

    def close(self):
        self.halt.set()
        if self.thread:
            self.thread.join(timeout=1)

    def status(self):
        try:
            size = sum(p.stat().st_size for p in (self.path, self.path.with_suffix(".sqlite3-journal")) if p.exists())
        except OSError:
            size = None
        return {**self.health, "queued": sum(q.qsize() for q in self.queues), "bytes": size}


store = None


def emit(kind, reason, *, module, level="INFO", details=None, exception=None, **identities):
    active = store
    if active is None:
        return
    threshold = os.getenv("DIAGNOSTICS_LEVEL", "INFO").upper()
    if (level in LEVELS[:3] and not kind.startswith(("motion.", "stop."))
            and LEVELS.index(level) < LEVELS.index(threshold if threshold in LEVELS else "INFO")):
        return
    error = None
    if exception is not None:
        frames = []
        tb = exception.__traceback__
        while tb is not None and len(frames) < 8:
            code = tb.tb_frame.f_code
            frames.append(f"{Path(code.co_filename).name}:{tb.tb_lineno}:{code.co_name}")
            tb = tb.tb_next
        error = {"type": type(exception).__name__, "frames": frames}
    active.offer({
        **context.get(), **identities, "schema_version": 1, "event_id": uuid4().hex,
        "occurred_at": utc(), "host_id": active.host_id, "source": identities.get("source", "host"),
        "service": "insightrover", "module": module, "level": level, "event_type": kind,
        "reason_code": reason, "context": details or {}, "exception": error,
    })


class DiagnosticMiddleware:
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope['type'] == 'websocket':
            began = time.monotonic()
            try:
                return await self.app(scope, receive, send)
            finally:
                endpoint = getattr(scope.get('endpoint'), '__name__', None)
                if endpoint:
                    emit('socket.closed', 'socket_ended', module=endpoint,
                         details={'elapsed_ms': (time.monotonic()-began)*1000})
        if scope['type'] != 'http':
            return await self.app(scope, receive, send)
        from ...core.diagnostic_context import request_context
        headers = {key.decode("latin1"): value.decode("latin1") for key, value in scope["headers"]
                   if key == b"x-request-id"}
        ids = request_context(headers)
        token = context.set(ids)
        began = time.monotonic()
        status = 500
        error = None

        async def reply(message):
            nonlocal status
            if message["type"] == "http.response.start":
                status = message["status"]
                message["headers"] = [*message.get("headers", []),
                                      (b"x-request-id", ids["request_id"].encode())]
            await send(message)

        try:
            await self.app(scope, receive, reply)
        except Exception as exc:
            error = exc
            raise
        finally:
            try:
                path = getattr(scope.get("route"), "path", "")
                if path.startswith(("/api/v1", "/api/control")) and (
                    status >= 400 or (path != '/api/v1/robots/{robot_id}/control'
                                      and not path.startswith(("/api/control", "/api/v1/diagnostics")))
                ):
                    endpoint = getattr(scope.get("endpoint"), "__name__", "http")
                    emit("http.failed" if error else "http.completed", f"http_{status}",
                         module=endpoint, level="ERROR" if status >= 500 else "WARN" if status >= 400 else "INFO",
                         details={"status_code": status, "elapsed_ms": round((time.monotonic()-began)*1000, 1)},
                         exception=error)
            finally:
                context.reset(token)
