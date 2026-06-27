def evaluate_mapping_quality(*, lidar, map_status, odom, tf_status, speed_scale):
    issues = []
    if not lidar.get("ok", False):
        issues.append("lidar")
    if not map_status.get("ok", False):
        issues.append("map")
    if not odom.get("ok", False):
        issues.append("odom")
    if not tf_status.get("ok", False):
        issues.append("tf")
    if float(speed_scale) > 0.25:
        issues.append("speed")

    if not issues:
        return {
            "ok": True,
            "level": "good",
            "message": "ok",
            "issues": [],
        }
    if any(item in issues for item in ("lidar", "odom", "tf")):
        level = "bad"
    else:
        level = "warn"

    return {
        "ok": False,
        "level": level,
        "message": ",".join(issues),
        "issues": issues,
    }
