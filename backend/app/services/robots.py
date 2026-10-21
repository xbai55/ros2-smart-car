"""机器人序列化。

数据库提供设备档案；传感器和运行状态只使用未过期的实时数据。
遥测缺失时报告离线，数值保持未知。
"""
from __future__ import annotations

from datetime import datetime
import time

from ..core.config import settings
from typing import Any, Mapping

from ..models.core import Robot


def _iso(value: datetime | None) -> str | None:
    return value.isoformat() if value else None


def serialize_robot(robot: Robot, realtime: Mapping[str, Any] | None = None) -> dict:
    rt: Mapping[str, Any] = realtime or {}
    timestamp = rt.get("updated_at", 0)
    try:
        fresh = bool(rt) and 0 <= time.time() - float(timestamp) <= settings.heartbeat_timeout_seconds
    except (TypeError, ValueError):
        fresh = False
    if not fresh:
        rt = {}
    stored_position = {}
    pose = rt.get("pose") or {}
    position = rt.get("position") or pose or stored_position
    return {
        "id": robot.id,
        "name": robot.name,
        "serial": robot.serial,
        "robot_code": robot.robot_code or robot.serial,
        "model": robot.model,
        "status": rt.get("status", "offline"),
        "mode": rt.get("mode"),
        "health": rt.get("health", "unknown"),
        "battery": rt.get("battery"),
        "speed": rt.get("speed"),
        "emergency_stop": rt.get("emergency_stop"),
        "pose": pose,
        "position": position,
        "network": rt.get("network") or {},
        "temperature": rt.get("temperature"),
        "detections": rt.get("detections", []),
        "current_task": robot.current_task,
        "current_map": robot.current_map,
        "last_seen": _iso(robot.last_seen),
        "last_heartbeat": _iso(robot.last_heartbeat),
        "created_at": _iso(robot.created_at),
        "updated_at": _iso(robot.updated_at),
        "source": "realtime" if rt else "unavailable",
    }


def status_payload(robot: Robot, realtime: Mapping[str, Any] | None, backend: str) -> dict:
    payload = serialize_robot(robot, realtime)
    payload["robot_id"] = robot.id
    payload["source"] = f"{backend}_cache" if payload["source"] == "realtime" else "unavailable"
    return payload
