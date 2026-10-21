"""机器人实时状态存储抽象。

生产环境使用 Redis（Robot Gateway 写入、FastAPI WebSocket 读取），
键位约定为 `robot:status:{robot_id}` 与 `robot:activity:{robot_id}`。
本地未安装 redis 依赖或未启动 Redis 时自动退回线程安全的内存实现，接口保持一致。
"""
import json
import threading
import time
from collections import defaultdict, deque
from typing import Any

from ..core.config import settings


class RealtimeStore:
    backend = "memory"

    def set_status(self, robot_id: str, status: dict[str, Any]) -> None:
        raise NotImplementedError

    def get_status(self, robot_id: str) -> dict[str, Any] | None:
        raise NotImplementedError

    def all_statuses(self) -> dict[str, dict[str, Any]]:
        raise NotImplementedError

    def add_activity(self, robot_id: str, event: dict[str, Any]) -> None:
        raise NotImplementedError

    def get_activity(self, robot_id: str, limit: int = 50) -> list[dict[str, Any]]:
        raise NotImplementedError

    def version(self, robot_id: str) -> float:
        raise NotImplementedError

    def clear_status(self, robot_id: str) -> None:
        raise NotImplementedError

    # 便于接口层判断数据来源
    def is_available(self) -> bool:
        return True


def _with_defaults(status: dict[str, Any]) -> dict[str, Any]:
    payload = dict(status)
    payload.setdefault("updated_at", time.time())
    return payload


class MemoryRealtimeStore(RealtimeStore):
    backend = "memory"

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._status: dict[str, dict[str, Any]] = {}
        self._activity: dict[str, deque] = defaultdict(lambda: deque(maxlen=200))

    def set_status(self, robot_id: str, status: dict[str, Any]) -> None:
        payload = _with_defaults(status)
        with self._lock:
            self._status[robot_id] = payload

    def get_status(self, robot_id: str) -> dict[str, Any] | None:
        with self._lock:
            current = self._status.get(robot_id)
            return dict(current) if current is not None else None

    def all_statuses(self) -> dict[str, dict[str, Any]]:
        with self._lock:
            return {k: dict(v) for k, v in self._status.items()}

    def version(self, robot_id: str) -> float:
        with self._lock:
            current = self._status.get(robot_id) or {}
            return float(current.get("updated_at", 0.0))

    def clear_status(self, robot_id: str) -> None:
        with self._lock:
            self._status.pop(robot_id, None)

    def add_activity(self, robot_id: str, event: dict[str, Any]) -> None:
        event = dict(event)
        event.setdefault("id", f"evt-{time.time_ns()}")
        event.setdefault("created_at", time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()))
        with self._lock:
            self._activity[robot_id].appendleft(event)

    def get_activity(self, robot_id: str, limit: int = 50) -> list[dict[str, Any]]:
        with self._lock:
            return [dict(e) for e in list(self._activity[robot_id])[:limit]]


class RedisRealtimeStore(RealtimeStore):
    """Redis 实现：状态以 JSON 字符串保存，活动流使用 List 保存最近 N 条。"""

    backend = "redis"
    _STATUS_KEY = "robot:status:{robot_id}"
    _ACTIVITY_KEY = "robot:activity:{robot_id}"
    _ACTIVITY_MAX = 200

    def __init__(self, client) -> None:
        self._client = client

    def is_available(self) -> bool:
        try:
            return bool(self._client.ping())
        except Exception:
            return False

    def set_status(self, robot_id: str, status: dict[str, Any]) -> None:
        payload = _with_defaults(status)
        self._client.set(
            self._STATUS_KEY.format(robot_id=robot_id),
            json.dumps(payload, ensure_ascii=False),
        )

    def get_status(self, robot_id: str) -> dict[str, Any] | None:
        raw = self._client.get(self._STATUS_KEY.format(robot_id=robot_id))
        if not raw:
            return None
        try:
            return json.loads(raw)
        except Exception:
            return None

    def all_statuses(self) -> dict[str, dict[str, Any]]:
        result: dict[str, dict[str, Any]] = {}
        for key in self._client.scan_iter("robot:status:*"):
            raw = self._client.get(key)
            if not raw:
                continue
            try:
                result[key.rsplit(":", 1)[-1]] = json.loads(raw)
            except Exception:
                continue
        return result

    def version(self, robot_id: str) -> float:
        status = self.get_status(robot_id) or {}
        try:
            return float(status.get("updated_at", 0.0))
        except (TypeError, ValueError):
            return 0.0

    def clear_status(self, robot_id: str) -> None:
        self._client.delete(self._STATUS_KEY.format(robot_id=robot_id))

    def add_activity(self, robot_id: str, event: dict[str, Any]) -> None:
        event = dict(event)
        event.setdefault("id", f"evt-{time.time_ns()}")
        event.setdefault("created_at", time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()))
        key = self._ACTIVITY_KEY.format(robot_id=robot_id)
        self._client.lpush(key, json.dumps(event, ensure_ascii=False))
        self._client.ltrim(key, 0, self._ACTIVITY_MAX - 1)

    def get_activity(self, robot_id: str, limit: int = 50) -> list[dict[str, Any]]:
        raw_items = self._client.lrange(
            self._ACTIVITY_KEY.format(robot_id=robot_id), 0, max(limit, 1) - 1
        )
        events = []
        for raw in raw_items:
            try:
                events.append(json.loads(raw))
            except Exception:
                continue
        return events


_store: RealtimeStore | None = None
_store_lock = threading.Lock()


def _build_store() -> RealtimeStore:
    if not settings.redis_enabled:
        return MemoryRealtimeStore()
    try:
        import redis  # type: ignore
    except Exception:
        return MemoryRealtimeStore()
    try:
        client = redis.Redis.from_url(
            settings.redis_url,
            socket_connect_timeout=settings.redis_socket_timeout,
            socket_timeout=settings.redis_socket_timeout,
            decode_responses=True,
        )
        client.ping()
        return RedisRealtimeStore(client)
    except Exception:
        return MemoryRealtimeStore()


def get_realtime_store() -> RealtimeStore:
    global _store
    if _store is None:
        with _store_lock:
            if _store is None:
                _store = _build_store()
    return _store


def reset_realtime_store() -> None:
    """测试或运行期切换后端时使用。"""
    global _store
    with _store_lock:
        _store = None


def realtime_backend() -> str:
    return get_realtime_store().backend
