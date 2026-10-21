"""Persistent drawing-to-map registration and named stops; no ROS dependency."""
import copy
import json
import math
import os
import tempfile
import threading
from pathlib import Path
from uuid import uuid4

DEFAULT_PLACES = [
    {"id": "teacher", "name": "老师处", "drawing": {"x": 1015.0, "y": 180.0}, "yaw": math.pi},
    {"id": "door", "name": "门口", "drawing": {"x": 1078.0, "y": 510.0}, "yaw": -math.pi / 2},
]

DEFAULT_DRAWING = {"id": "builtin-lab", "name": "实验室平面图", "width": 1208,
                   "height": 552, "kind": "builtin"}


def drawing_descriptor(value=None):
    """An image is a visual reference, never an inferred occupancy layer."""
    if value is None:
        return dict(DEFAULT_DRAWING)
    if not isinstance(value, dict) or value.get("kind") not in {"builtin", "uploaded"}:
        raise ValueError("平面图信息无效")
    if value["kind"] == "builtin":
        if (value.get("id") != DEFAULT_DRAWING["id"] or
                value.get("width") != 1208 or value.get("height") != 552):
            raise ValueError("内置平面图信息无效")
        return dict(DEFAULT_DRAWING)
    ident, name = value.get("id"), value.get("name")
    if not isinstance(ident, str) or not ident.strip() or len(ident) > 128:
        raise ValueError("平面图标识无效")
    if not isinstance(name, str) or not name.strip() or len(name) > 128:
        raise ValueError("平面图名称无效")
    width, height = finite_number(value.get("width")), finite_number(value.get("height"))
    if width <= 0 or height <= 0 or not width.is_integer() or not height.is_integer() or width * height > 16_000_000:
        raise ValueError("平面图尺寸无效")
    result = {"id": ident, "name": name.strip(), "width": int(width), "height": int(height), "kind": "uploaded"}
    if value.get("revision") is not None:
        if not isinstance(value["revision"], str) or len(value["revision"]) > 256:
            raise ValueError("平面图版本无效")
        result["revision"] = value["revision"]
    return result


def drawing_identity(value=None):
    drawing = drawing_descriptor(value)
    return tuple(drawing.get(key) for key in ("kind", "id", "width", "height")) + (drawing.get("revision") or "",)


def finite_number(value):
    if isinstance(value, bool):
        raise ValueError("坐标必须为有限数值")
    try:
        value = float(value)
    except (ValueError, TypeError, OverflowError) as exc:
        raise ValueError("坐标必须为有限数值") from exc
    if not math.isfinite(value):
        raise ValueError("坐标必须为有限数值")
    return value


def point(value):
    if not isinstance(value, dict):
        raise ValueError("坐标格式无效")
    return {"x": finite_number(value["x"]), "y": finite_number(value["y"])}


def map_key(snapshot):
    info = snapshot["info"]
    origin = info["origin"]
    frame = snapshot.get("header", {}).get("frame_id") or "map"
    geometry = (f"{frame}:{info['width']}:{info['height']}:{info['resolution']:.6f}:"
                f"{origin['x']:.6f}:{origin['y']:.6f}:{origin['yaw']:.6f}")
    identity = snapshot.get("asset_digest") or snapshot.get("session_id")
    return geometry + (f":{identity}" if identity else "")


def transform_point(value, matrix):
    p = point(value)
    return {"x": matrix[0] * p["x"] + matrix[1] * p["y"] + matrix[2],
            "y": matrix[3] * p["x"] + matrix[4] * p["y"] + matrix[5]}


def solve_three(matrix, vector):
    rows = [list(row) + [value] for row, value in zip(matrix, vector)]
    for col in range(3):
        pivot = max(range(col, 3), key=lambda row: abs(rows[row][col]))
        if abs(rows[pivot][col]) < 1e-9:
            raise ValueError("对齐点不能位于同一直线，请选择分散的四个位置")
        rows[col], rows[pivot] = rows[pivot], rows[col]
        scale = rows[col][col]
        rows[col] = [value / scale for value in rows[col]]
        for row in range(3):
            if row != col:
                factor = rows[row][col]
                rows[row] = [a - factor * b for a, b in zip(rows[row], rows[col])]
    return [rows[row][3] for row in range(3)]


def fit_calibration(anchors, snapshot, drawing=None):
    if not isinstance(anchors, list) or len(anchors) != 4:
        raise ValueError("请提供四组平面图与实车地图的对应点")
    drawing = drawing_descriptor(drawing)
    pairs = [{"drawing": point(p["drawing"]), "world": point(p["world"])} for p in anchors]
    for pair in pairs:
        if not 0 <= pair["drawing"]["x"] <= drawing["width"] or not 0 <= pair["drawing"]["y"] <= drawing["height"]:
            raise ValueError("对齐点超出平面图")
    # Reject narrowly clustered anchors even if a least-squares fit is possible.
    normalized = [(p["drawing"]["x"] / drawing["width"], p["drawing"]["y"] / drawing["height"]) for p in pairs]
    area = max(abs((b[0]-a[0])*(c[1]-a[1])-(b[1]-a[1])*(c[0]-a[0]))
               for a in normalized for b in normalized for c in normalized)
    if area < .02:
        raise ValueError("对齐点不能集中或位于同一直线，请选择分散的四个位置")
    if any(math.hypot(a[0]-b[0], a[1]-b[1]) < 1e-4 for i, a in enumerate(normalized) for b in normalized[i+1:]):
        raise ValueError("对齐点不能重复，请选择四个不同位置")
    # Least-squares affine fit: all four observations contribute to the transform.
    # Normalize pixels first so high-resolution images remain numerically stable.
    design = [[x, y, 1] for x, y in normalized]
    normal = [[sum(row[i] * row[j] for row in design) for j in range(3)] for i in range(3)]
    matrix = []
    for axis in ("x", "y"):
        coefficients = solve_three(normal, [sum(row[i] * p["world"][axis] for row, p in zip(design, pairs)) for i in range(3)])
        matrix.extend([coefficients[0] / drawing["width"], coefficients[1] / drawing["height"], coefficients[2]])
    determinant = matrix[0] * matrix[4] - matrix[1] * matrix[3]
    if abs(determinant) < 1e-10:
        raise ValueError("实车地图的对应点不能位于同一直线")
    errors = [math.hypot(*(transform_point(p["drawing"], matrix)[axis] - p["world"][axis] for axis in ("x", "y"))) for p in pairs]
    error = max(errors)
    if error > 0.10:
        raise ValueError(f"对齐误差 {error:.2f} m 超过 0.10 m；请核对对应点或修正概图比例")
    return {"map_key": map_key(snapshot), "matrix": matrix, "anchors": pairs, "drawing": drawing,
            "max_error": error, "rms_error": math.sqrt(sum(e * e for e in errors) / len(errors)), "errors": errors}


def validate_map_goal(goal, snapshot, radius=0.25):
    """Reject unknown, occupied and footprint-clearance violations before Nav2."""
    info = snapshot["info"]
    origin, resolution = info["origin"], float(info["resolution"])
    width, height = int(info["width"]), int(info["height"])
    if resolution <= 0 or len(snapshot["data"]) != width * height:
        raise ValueError("地图数据无效")
    p = point(goal)
    dx, dy = p["x"] - origin["x"], p["y"] - origin["y"]
    c, s = math.cos(origin["yaw"]), math.sin(origin["yaw"])
    gx, gy = (c * dx + s * dy) / resolution, (-s * dx + c * dy) / resolution
    cx, cy = math.floor(gx), math.floor(gy)
    if not 0 <= cx < width or not 0 <= cy < height:
        raise ValueError("目标超出实车地图")
    mask = snapshot.get('keepout')
    if mask is not None:
        from .keepout import validate_keepout
        validate_keepout(snapshot)
        padding = math.ceil(radius/resolution)
        if any(mask[y*width+x] for y in range(max(0,cy-padding),min(height,cy+padding+1)) for x in range(max(0,cx-padding),min(width,cx+padding+1))):
            raise ValueError('目标位于禁行区域或车体安全边界内')
    span = math.ceil(radius / resolution) + 1
    for y in range(cy - span, cy + span + 1):
        for x in range(cx - span, cx + span + 1):
            if math.hypot(x + .5 - gx, y + .5 - gy) * resolution > radius + resolution / math.sqrt(2):
                continue
            if not 0 <= x < width or not 0 <= y < height:
                raise ValueError("目标离地图边界过近")
            value = snapshot["data"][y * width + x]
            if value < 0 or value >= 25:
                raise ValueError("目标位于障碍物、未知区域或安全边界内，请选择附近空地")
    return p


class NavigationConfigStore:
    def __init__(self, path):
        self.path = Path(path).expanduser()
        self.lock = threading.RLock()
        self.data = {"calibration": None, "places": copy.deepcopy(DEFAULT_PLACES)}
        if self.path.is_file():
            payload = json.loads(self.path.read_text(encoding="utf-8"))
            if not isinstance(payload, dict) or not isinstance(payload.get("places"), list):
                raise ValueError("预设地点文件无效")
            self.data = payload

    def snapshot(self):
        with self.lock:
            return copy.deepcopy(self.data)

    def _save(self, data):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = None
        try:
            with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=self.path.parent, delete=False) as handle:
                temporary = handle.name
                json.dump(data, handle, ensure_ascii=False, allow_nan=False)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, self.path)
            self.data = data
        finally:
            if temporary and os.path.exists(temporary):
                os.unlink(temporary)

    def calibrate(self, anchors, snapshot, drawing=None):
        calibration = fit_calibration(anchors, snapshot, drawing)
        with self.lock:
            data = self.snapshot()
            previous = data.get("calibration") or {}
            if drawing_identity(previous.get("drawing")) != drawing_identity(calibration["drawing"]):
                data["places"] = copy.deepcopy(DEFAULT_PLACES) if calibration["drawing"]["kind"] == "builtin" else []
            data["calibration"] = calibration
            self._save(data)
        return self.snapshot()

    def invalidate_calibration(self):
        """A restarted SLAM session can reuse metadata but establish a new frame.

        Keep the image identity and pixel presets; none are executable until a
        new fit replaces this explicitly invalidated registration.
        """
        with self.lock:
            data = self.snapshot()
            if data.get("calibration") is not None:
                data["calibration"]["invalidated"] = True
                self._save(data)
            return self.snapshot()

    def add_place(self, payload, snapshot, radius=.25):
        name = str(payload.get("name", "")).strip()
        if not name or len(name) > 40:
            raise ValueError("地点名称需为 1–40 个字符")
        drawing = point(payload["drawing"])
        yaw = finite_number(payload.get("yaw", 0))
        with self.lock:
            data = self.snapshot()
            calibration = data.get("calibration")
            if (snapshot is None or calibration is None or calibration.get("invalidated") or
                    calibration["map_key"] != map_key(snapshot)):
                raise ValueError("请先完成当前地图的对齐")
            # A second browser may have switched the active reference drawing.
            # Validate optional caller context under the same lock as persistence.
            if "map_key" in payload and payload["map_key"] != map_key(snapshot):
                raise ValueError("地图已变化，请重新选择地点")
            if "calibration_matrix" in payload and payload["calibration_matrix"] != calibration["matrix"]:
                raise ValueError("地图对齐已变化，请刷新后重新保存地点")
            if ("calibration_drawing" in payload and
                    drawing_identity(payload["calibration_drawing"]) != drawing_identity(calibration.get("drawing"))):
                raise ValueError("平面图已变化，请刷新后重新保存地点")
            if not valid_drawing_point(drawing, calibration.get("drawing")):
                raise ValueError("地点应设在平面图范围内的空地")
            validate_map_goal(transform_point(drawing, calibration["matrix"]), snapshot, radius)
            if any(place["name"] == name for place in data["places"]):
                raise ValueError("已有同名地点")
            if len(data["places"]) >= 50:
                raise ValueError("最多保存 50 个预设地点")
            data["places"].append({"id": str(uuid4()), "name": name, "drawing": drawing, "yaw": yaw})
            self._save(data)
        return self.snapshot()
    def remove_place(self, place_id):
        with self.lock:
            data = self.snapshot()
            if not any(p["id"] == place_id for p in data["places"]):
                raise ValueError("地点不存在")
            data["places"] = [p for p in data["places"] if p["id"] != place_id]
            self._save(data)
        return self.snapshot()


def valid_drawing_point(p, drawing=None):
    descriptor = drawing_descriptor(drawing)
    if descriptor["kind"] == "uploaded":
        return 0 <= p["x"] < descriptor["width"] and 0 <= p["y"] < descriptor["height"]
    if not 18 <= p["x"] <= 1190 or not 18 <= p["y"] <= 534:
        return False
    for ax, ay, bx, by in ((0, 165, 912, 165), (912, 88, 912, 243), (0, 398, 912, 398)):
        dx, dy = bx - ax, by - ay
        t = max(0, min(1, ((p["x"] - ax) * dx + (p["y"] - ay) * dy) / (dx * dx + dy * dy)))
        if math.hypot(p["x"] - ax - t * dx, p["y"] - ay - t * dy) <= 28:
            return False
    return True
