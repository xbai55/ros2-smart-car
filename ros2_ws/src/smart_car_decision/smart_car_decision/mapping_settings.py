"""Validated, persistent operator settings; independent of ROS."""
import json
import math
import os
import threading
from pathlib import Path

LASER_RANGES = (0.5, 1.0, 3.0, 6.0)


def turn_speed(value):
    if isinstance(value, bool):
        raise ValueError("转弯速度必须为 0.05–0.60 rad/s")
    try:
        value = float(value)
    except (TypeError, ValueError, OverflowError):
        raise ValueError("转弯速度必须为 0.05–0.60 rad/s") from None
    if not math.isfinite(value) or not .05 <= value <= .6:
        raise ValueError("转弯速度必须为 0.05–0.60 rad/s")
    return round(value, 3)


def laser_range(value):
    if isinstance(value, bool):
        raise ValueError("建图距离请选择 0.5、1、3 或 6 米")
    try:
        value = float(value)
    except (TypeError, ValueError, OverflowError):
        raise ValueError("建图距离请选择 0.5、1、3 或 6 米") from None
    if value not in LASER_RANGES:
        raise ValueError("建图距离请选择 0.5、1、3 或 6 米")
    return value


class MappingSettings:
    def __init__(self, path=None):
        self.path = Path(path).expanduser() if path else None
        self.lock = threading.RLock()
        self._value = {"turn_speed": .15, "max_laser_range": 3.0}
        if self.path and self.path.exists():
            raw = json.loads(self.path.read_text(encoding="utf-8"))
            self._value = {"turn_speed": turn_speed(raw["turn_speed"]),
                           "max_laser_range": laser_range(raw["max_laser_range"])}

    def snapshot(self):
        with self.lock:
            return dict(self._value)

    def update(self, **changes):
        if not changes or set(changes) - self._value.keys():
            raise ValueError("无效的运动或建图设置")
        validated = {key: (turn_speed(value) if key == "turn_speed" else laser_range(value))
                     for key, value in changes.items()}
        with self.lock:
            value = {**self._value, **validated}
            if self.path:
                self.path.parent.mkdir(parents=True, exist_ok=True)
                temporary = self.path.with_suffix(self.path.suffix + ".tmp")
                try:
                    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")
                    os.replace(temporary, self.path)
                finally:
                    temporary.unlink(missing_ok=True)
            self._value = value
            return dict(value)
