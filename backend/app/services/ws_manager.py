"""WebSocket 连接管理。

使用房间（room）概念支持按机器人订阅：机器人状态通道按 robot_id 分房间，
通知通道使用全局房间。业务层可通过 broadcast 主动推送，无需轮询。
"""
from __future__ import annotations

import asyncio
import threading
from collections import defaultdict
from typing import Any

from fastapi import WebSocket

GLOBAL_ROOM = "__all__"


class ConnectionManager:
    def __init__(self, channel: str) -> None:
        self.channel = channel
        self._lock = threading.Lock()
        self._rooms: dict[str, set[WebSocket]] = defaultdict(set)

    def counts(self) -> dict[str, int]:
        with self._lock:
            return {room: len(items) for room, items in self._rooms.items() if items}

    def total(self) -> int:
        with self._lock:
            return sum(len(items) for items in self._rooms.values())

    async def connect(self, websocket: WebSocket, room: str = GLOBAL_ROOM) -> None:
        await websocket.accept()
        with self._lock:
            self._rooms[room].add(websocket)

    def disconnect(self, websocket: WebSocket, room: str = GLOBAL_ROOM) -> None:
        with self._lock:
            self._rooms[room].discard(websocket)
            if not self._rooms[room]:
                self._rooms.pop(room, None)

    async def send(self, websocket: WebSocket, payload: dict[str, Any]) -> bool:
        try:
            await websocket.send_json(payload)
            return True
        except Exception:
            return False

    async def broadcast(self, payload: dict[str, Any], room: str | None = None) -> int:
        with self._lock:
            if room is None:
                targets = {ws for items in self._rooms.values() for ws in items}
            else:
                targets = set(self._rooms.get(room, set()))
        results = await asyncio.gather(
            *(self.send(ws, payload) for ws in targets), return_exceptions=True
        )
        return sum(1 for ok in results if ok is True)


robot_manager = ConnectionManager("robot_status")
notification_manager = ConnectionManager("notifications")


def managers_status() -> dict[str, dict[str, int]]:
    return {
        "robots": robot_manager.counts(),
        "notifications": notification_manager.counts(),
    }
