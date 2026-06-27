def evaluate_tf_health(*, ok, message, checked_at, parent_frame, child_frame):
    return {
        "ok": bool(ok),
        "message": str(message or ("ok" if ok else "unavailable")),
        "checked_at": None if checked_at is None else float(checked_at),
        "parent_frame": str(parent_frame or ""),
        "child_frame": str(child_frame or ""),
    }
