from collections import deque
from dataclasses import dataclass
from math import isfinite


@dataclass(frozen=True)
class ScanQuality:
    total_count: int
    valid_count: int
    valid_ratio: float


def scan_quality(scan):
    ranges = list(scan.ranges or [])
    valid_count = sum(
        1
        for value in ranges
        if isfinite(value) and scan.range_min <= value <= scan.range_max
    )
    total_count = len(ranges)
    ratio = valid_count / total_count if total_count else 0.0
    return ScanQuality(total_count, valid_count, ratio)


class ScanRateWindow:
    def __init__(self, max_samples=20):
        self._timestamps = deque(maxlen=max(2, int(max_samples)))

    def add(self, timestamp):
        self._timestamps.append(float(timestamp))

    @property
    def rate_hz(self):
        if len(self._timestamps) < 2:
            return 0.0
        elapsed = self._timestamps[-1] - self._timestamps[0]
        if elapsed <= 0.0:
            return 0.0
        return (len(self._timestamps) - 1) / elapsed


def evaluate_lidar_health(
    *,
    last_scan_time,
    now,
    timeout_sec,
    rate_hz,
    valid_count,
    valid_ratio,
    min_valid_ratio,
    frame_id,
):
    if last_scan_time is None:
        age = None
        message = "no_data"
    else:
        age = max(0.0, float(now) - float(last_scan_time))
        if age > float(timeout_sec):
            message = "stale"
        elif float(valid_ratio) < float(min_valid_ratio):
            message = "insufficient_valid_points"
        else:
            message = "ok"

    return {
        "ok": message == "ok",
        "message": message,
        "scan_age_sec": None if age is None else round(age, 3),
        "scan_rate_hz": round(float(rate_hz), 2),
        "valid_count": int(valid_count),
        "valid_ratio": round(float(valid_ratio), 3),
        "frame_id": str(frame_id or ""),
    }
