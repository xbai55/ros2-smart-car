"""Combine measured occupancy with registered solid laboratory barriers."""
import math
import threading

from .navigation_config import drawing_descriptor, drawing_identity, map_key

BARRIERS = [(0, 0, 1208, 0, 4), (0, 0, 0, 552, 4), (1208, 0, 1208, 552, 4),
            (0, 552, 1007, 552, 4), (1148, 552, 1208, 552, 4),
            (0, 165, 912, 165, 23), (912, 88, 912, 243, 20), (0, 398, 912, 398, 23)]


def registered_obstacle_map(snapshot, calibration):
    if snapshot is None:
        return None
    result = {**snapshot, "data": list(snapshot["data"])}
    if not calibration or calibration.get("invalidated") or calibration["map_key"] != map_key(snapshot):
        result["data"] = [100] * len(result["data"])
        return result
    # Uploaded floor plans contain arbitrary artwork, not measured obstacles.
    # In particular, never project the builtin laboratory benches onto them.
    if drawing_descriptor(calibration.get("drawing"))["kind"] == "uploaded":
        return result
    a, b, c, d, e, f = calibration["matrix"]
    det = a * e - b * d
    if abs(det) < 1e-10:
        raise ValueError("对齐参数无效")
    info = snapshot["info"]
    origin, resolution = info["origin"], info["resolution"]
    cos, sin = math.cos(origin["yaw"]), math.sin(origin["yaw"])
    # Account for an occupancy cell's area rather than only its center.
    padding = resolution / math.sqrt(2) * math.sqrt(a*a + b*b + d*d + e*e) / abs(det)
    for ax, ay, bx, by, radius in BARRIERS:
        margin = radius + padding
        corners = []
        for px in (min(ax, bx) - margin, max(ax, bx) + margin):
            for py in (min(ay, by) - margin, max(ay, by) + margin):
                wx, wy = a * px + b * py + c - origin["x"], d * px + e * py + f - origin["y"]
                corners.append(((cos * wx + sin * wy) / resolution, (-sin * wx + cos * wy) / resolution))
        left = max(0, math.floor(min(p[0] for p in corners)))
        right = min(info["width"], math.ceil(max(p[0] for p in corners)))
        bottom = max(0, math.floor(min(p[1] for p in corners)))
        top = min(info["height"], math.ceil(max(p[1] for p in corners)))
        for y in range(bottom, top):
            for x in range(left, right):
                wx = origin["x"] + ((x + .5) * cos - (y + .5) * sin) * resolution - c
                wy = origin["y"] + ((x + .5) * sin + (y + .5) * cos) * resolution - f
                px, py = (e * wx - b * wy) / det, (-d * wx + a * wy) / det
                if min(ax, bx) - margin <= px <= max(ax, bx) + margin and min(ay, by) - margin <= py <= max(ay, by) + margin:
                    result["data"][y * info["width"] + x] = 100
    return result


class NavigationMapStore:
    def __init__(self):
        self.lock = threading.RLock()
        self.value = None
        self.version = None

    def update(self, snapshot, calibration):
        version = None if snapshot is None else (snapshot.get("updated_at"), map_key(snapshot), tuple(calibration["matrix"]) if calibration else None, calibration.get("map_key") if calibration else None,
                                                drawing_identity(calibration.get("drawing")) if calibration else None,
                                                bool(calibration.get("invalidated")) if calibration else False)
        with self.lock:
            if self.value is not None and version == self.version:
                return False
            self.value = registered_obstacle_map(snapshot, calibration)
            self.version = version
            return True

    def snapshot(self):
        with self.lock:
            return self.value
