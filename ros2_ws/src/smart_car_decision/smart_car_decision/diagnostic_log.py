"""Best-effort vehicle diagnostic transport. Only writer threads touch disk."""
import json
import os
import re
import time
from contextvars import ContextVar
from datetime import datetime, timezone
from itertools import count
from pathlib import Path
from queue import Empty, Full, Queue
from threading import Event, Thread
from uuid import uuid4

ROOT = Path(os.getenv("VEHICLE_DIAGNOSTICS_DIR", str(Path.home() / ".local/share/insightrover/diagnostics")))
MAX_SEGMENT = 1024**2
MAX_RECORD = 4096
SLOTS = ("controller", "web", "launch")
LEVELS = ("DEBUG", "INFO", "WARN", "ERROR", "CRITICAL")
IDENT = re.compile(r"[A-Za-z0-9_-]{1,64}\Z")
PARENT = re.compile(r"00-([0-9a-f]{32})-([0-9a-f]{16})-[0-9a-f]{2}\Z")
request_ids = ContextVar("vehicle_diagnostic_ids", default={})


def correlation(headers):
    parent = PARENT.fullmatch(headers.get("traceparent", ""))
    request = headers.get("x-request-id", "")
    result = {}
    if parent and int(parent[1], 16) and int(parent[2], 16):
        result.update(trace_id=parent[1], span_id=parent[2])
    if IDENT.fullmatch(request):
        result["request_id"] = request
    run = headers.get('x-insightrover-run-id', '')
    if IDENT.fullmatch(run):
        result['run_id'] = run
    return result


def wire_ids(value):
    if not isinstance(value, dict):
        return {}
    return {key: val for key, val in value.items()
            if key in {"trace_id", "request_id", "span_id", "run_id", "episode_id"}
            and isinstance(val, str) and IDENT.fullmatch(val)}


def segment(root, channel, previous=False):
    return root / (channel + (".previous" if previous else "") + ".jsonl")


class DiagnosticLog:
    def __init__(self, slot, root=ROOT, *, max_segment=MAX_SEGMENT):
        self.slot, self.root, self.max_segment = slot, Path(root), max_segment
        self.boot = uuid4().hex
        self.instance_id = None
        self.seq = count(1)
        self.queues = (Queue(256), Queue(128))
        self.closed = Event()
        self.health = {"dropped": 0, "invalid": 0, "write_failed": 0, "last_write": None}
        self.enabled = os.getenv("VEHICLE_DIAGNOSTICS_ENABLED", "1") != "0"
        minimum = os.getenv("DIAGNOSTICS_LEVEL", "INFO").upper()
        self.minimum = LEVELS.index(minimum) if minimum in LEVELS else 1
        self.thread = None
        if self.enabled:
            self.thread = Thread(target=self._run, name=f"diag-{slot}", daemon=True)
            self.thread.start()

    def emit(self, kind, reason, *, details=None, level="INFO", ids=None):
        if not self.enabled:
            return
        critical = kind.startswith(("motion.", "stop.")) or level in ("ERROR", "CRITICAL")
        if not critical and LEVELS.index(level) < self.minimum:
            return
        queue = self.queues[int(critical)]
        try:
            queue.put_nowait((time.time(), next(self.seq), kind, reason, details or {},
                              level, ids if ids is not None else request_ids.get()))
        except Full:
            self.health["dropped"] += 1

    def close(self):
        self.closed.set()
        if self.thread is not None:
            self.thread.join(.5)

    def _append(self, lane, value):
        timestamp, seq, kind, reason, details, level, ids = value
        row = {
            **wire_ids(ids), "schema_version": 1, "event_id": f"{self.boot}-{seq}",
            "host_id": self.boot, "occurred_at": datetime.fromtimestamp(timestamp, timezone.utc).isoformat(),
            "source": "jetson", "service": "smart_car_decision", "module": self.slot,
            "level": level, "event_type": kind, "reason_code": reason, "context": details,
        }
        line = (json.dumps(row, ensure_ascii=False, allow_nan=False) + "\n").encode()
        if len(line) > min(MAX_RECORD, self.max_segment):
            self.health["invalid"] += 1
            return
        self.root.mkdir(mode=0o700, parents=True, exist_ok=True)
        path = segment(self.root, f"{self.slot}-{lane}")
        if path.exists() and path.stat().st_size + len(line) + 1 > self.max_segment:
            path.replace(segment(self.root, f"{self.slot}-{lane}", True))
        with path.open('a+b') as file:
            if file.tell():
                file.seek(-1, os.SEEK_END)
                if file.read(1) != b'\n':
                    if file.tell() + len(line) + 1 > self.max_segment:
                        self.health['write_failed'] += 1
                        return
                    file.write(b'\n')
            file.write(line)
        self.health["last_write"] = row["occurred_at"]

    def _run(self):
        cleanup_at = 0
        instance_retry_at = 0
        while not self.closed.is_set() or any(not q.empty() for q in self.queues):
            work = False
            if self.slot == 'web' and self.instance_id is None and time.monotonic() >= instance_retry_at:
                instance_retry_at = time.monotonic() + 30
                try:
                    self.root.mkdir(mode=0o700, parents=True, exist_ok=True)
                    marker = self.root / 'instance-id'
                    try:
                        with marker.open(encoding='ascii') as stream:
                            self.instance_id = stream.read(33).strip()
                    except FileNotFoundError:
                        value = uuid4().hex
                        with marker.open('x', encoding='ascii') as stream:
                            stream.write(value)
                        self.instance_id = value
                except (OSError, UnicodeError):
                    self.health['write_failed'] += 1
            for lane in (1, 0):
                for _ in range(32):
                    try:
                        item = self.queues[lane].get_nowait()
                    except Empty:
                        break
                    work = True
                    try:
                        self._append(lane, item)
                    except OSError:
                        self.health["write_failed"] += 1
                    except (TypeError, ValueError, OverflowError):
                        self.health["invalid"] += 1
            if time.monotonic() >= cleanup_at:
                cleanup_at = time.monotonic() + 30
                for lane in (1, 0):
                    for previous in (False, True):
                        path = segment(self.root, f"{self.slot}-{lane}", previous)
                        try:
                            if path.stat().st_mtime < time.time() - retention_seconds():
                                path.unlink()
                        except OSError:
                            pass
            if not work:
                self.closed.wait(.1)


def retention_seconds():
    try:
        return max(1, min(168, int(os.getenv("VEHICLE_DIAGNOSTICS_HOURS", "72")))) * 3600
    except ValueError:
        return 72 * 3600


def read_page(cursors, root=ROOT, limit=64):
    """Read at most two bounded segments per known channel; cursors are event IDs."""
    events, next_cursors, gaps = [], {}, []
    invalid = 0
    for lane in (1, 0):
        for slot in SLOTS:
            key = f"{slot}-{lane}"
            cursor = cursors.get(key)
            rows = []
            for previous in (True, False):
                path = segment(root, key, previous)
                try:
                    if path.stat().st_size > MAX_SEGMENT:
                        invalid += 1
                        continue
                    with path.open("rb") as file:
                        remaining = MAX_SEGMENT
                        while remaining > 0:
                            line = file.readline(min(remaining, MAX_RECORD + 1))
                            if not line:
                                break
                            remaining -= len(line)
                            if len(line) > MAX_RECORD or not line.endswith(b"\n"):
                                invalid += 1
                                continue
                            try:
                                value = json.loads(line)
                                ident = value.get("event_id")
                                if not isinstance(ident, str) or not IDENT.fullmatch(ident):
                                    raise ValueError("invalid event")
                                stamp = datetime.fromisoformat(value["occurred_at"])
                                if stamp.tzinfo is not None and stamp.timestamp() >= time.time() - retention_seconds():
                                    rows.append(value)
                            except (ValueError, AttributeError, TypeError, KeyError, OverflowError):
                                invalid += 1
                except FileNotFoundError:
                    pass
                except OSError:
                    gaps.append(key)
            if cursor:
                for index, row in enumerate(rows):
                    if row["event_id"] == cursor:
                        rows = rows[index+1:]
                        break
                else:
                    gaps.append(key)
            quota = max(1, limit // 6)
            selected = rows[:min(quota, limit - len(events))]
            events.extend(selected)
            if selected:
                next_cursors[key] = selected[-1]["event_id"]
            elif cursor and key not in gaps:
                next_cursors[key] = cursor
    return {"events": events, "cursors": next_cursors, "gaps": sorted(set(gaps)), "invalid": invalid}
