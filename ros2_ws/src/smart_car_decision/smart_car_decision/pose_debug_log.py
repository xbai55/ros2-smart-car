import json
import threading
import time
from collections import deque
from pathlib import Path


class PoseDebugLog:
    def __init__(self, path="/tmp/smart_car_logs/pose_debug.jsonl", max_entries=1200):
        self.path = Path(path)
        self.max_entries = int(max_entries)
        self._lock = threading.Lock()
        self._entries = deque(maxlen=self.max_entries)

    def append_status(self, status):
        entry = {
            "logged_at": round(time.time(), 4),
            "mode": status.get("mode", ""),
            "last_command": status.get("last_command", ""),
            "speed_scale": status.get("speed_scale", 0.0),
            "map_pose": status.get("map_pose", {}),
            "odom": status.get("odom", {}),
            "cmd_vel": status.get("cmd_vel", {}),
            "tf": status.get("tf", {}),
            "map": status.get("map", {}),
            "updated_at": status.get("updated_at"),
        }
        with self._lock:
            self._entries.append(entry)
            self._write_line(entry)
        return entry

    def clear(self):
        with self._lock:
            self._entries.clear()
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self.path.write_text("", encoding="utf-8")

    def snapshot(self, limit=None):
        with self._lock:
            entries = list(self._entries)
        if limit is not None:
            entries = entries[-int(limit):]
        return {
            "ok": True,
            "count": len(entries),
            "path": str(self.path),
            "entries": entries,
        }

    def _write_line(self, entry):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(entry, ensure_ascii=False, sort_keys=True) + "\n")
