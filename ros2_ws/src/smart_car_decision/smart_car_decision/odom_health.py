def evaluate_odom_health(
    *,
    last_odom_time,
    now,
    timeout_sec,
    frame_id,
    child_frame_id,
    linear_speed,
    angular_speed,
):
    if last_odom_time is None:
        return {
            "ok": False,
            "message": "no_odom",
            "odom_age_sec": None,
            "frame_id": frame_id or "",
            "child_frame_id": child_frame_id or "",
            "linear_speed": 0.0,
            "angular_speed": 0.0,
        }

    age = max(0.0, float(now) - float(last_odom_time))
    ok = age <= timeout_sec and bool(frame_id) and bool(child_frame_id)
    if age > timeout_sec:
        message = "stale"
    elif not frame_id or not child_frame_id:
        message = "missing_frame"
    else:
        message = "ok"

    return {
        "ok": ok,
        "message": message,
        "odom_age_sec": round(age, 3),
        "frame_id": frame_id or "",
        "child_frame_id": child_frame_id or "",
        "linear_speed": round(float(linear_speed), 3),
        "angular_speed": round(float(angular_speed), 3),
    }
