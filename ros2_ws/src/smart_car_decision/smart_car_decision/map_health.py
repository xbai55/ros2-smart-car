def evaluate_map_health(
    *, last_map_time, now, timeout_sec, width, height, resolution, frame_id
):
    if last_map_time is None:
        age = None
        message = "no_map"
    else:
        age = max(0.0, float(now) - float(last_map_time))
        if age > float(timeout_sec):
            message = "stale"
        elif int(width) <= 0 or int(height) <= 0 or float(resolution) <= 0.0:
            message = "invalid_map"
        else:
            message = "ok"

    return {
        "ok": message == "ok",
        "message": message,
        "map_age_sec": None if age is None else round(age, 3),
        "width": int(width),
        "height": int(height),
        "resolution": round(float(resolution), 4),
        "frame_id": str(frame_id or ""),
    }
