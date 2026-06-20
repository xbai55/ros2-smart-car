DEFAULT_COLOR_CONFIG = {
    "name": "green",
    "hsv_low": [35, 60, 60],
    "hsv_high": [90, 255, 255],
}


def normalize_color_config(payload):
    payload = payload or {}
    low = _normalize_hsv_triplet(payload.get("hsv_low"), DEFAULT_COLOR_CONFIG["hsv_low"])
    high = _normalize_hsv_triplet(payload.get("hsv_high"), DEFAULT_COLOR_CONFIG["hsv_high"])
    return {
        "name": str(payload.get("name") or "custom").strip()[:32] or "custom",
        "hsv_low": low,
        "hsv_high": high,
    }


def _normalize_hsv_triplet(values, fallback):
    if not isinstance(values, (list, tuple)) or len(values) != 3:
        values = fallback
    return [
        _clamp_int(values[0], 0, 179),
        _clamp_int(values[1], 0, 255),
        _clamp_int(values[2], 0, 255),
    ]


def _clamp_int(value, minimum, maximum):
    try:
        number = int(round(float(value)))
    except (TypeError, ValueError):
        number = minimum
    return max(minimum, min(maximum, number))
