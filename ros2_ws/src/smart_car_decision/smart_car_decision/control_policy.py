VALID_MODES = {
    "stop",
    "manual",
    "auto",
    "mapping",
    "navigation",
    "color_track",
    "object_follow",
}

VALID_MANUAL_COMMANDS = {
    "forward",
    "backward",
    "left",
    "right",
    "turn_l",
    "turn_r",
    "turn_left",
    "turn_right",
    "stop",
}


def zero_motion():
    return {"linear_x": 0.0, "linear_y": 0.0, "angular_z": 0.0}


def normalize_mode(value):
    mode = str(value or "").strip().lower().replace("-", "_").replace(" ", "_")
    return mode if mode in VALID_MODES else "stop"


def normalize_manual_command(value):
    command = str(value or "").strip().lower().replace("-", "_").replace(" ", "_")
    return command if command in VALID_MANUAL_COMMANDS else ""


def clamp(value, low, high):
    return max(low, min(high, value))


def decide_motion(
    *,
    mode,
    emergency_stop,
    front_distance,
    detection,
    manual_command,
    lane_offset,
    has_recent_detection,
    has_recent_manual,
    has_recent_lane,
    has_recent_scan=True,
    obstacle_stop_distance=0.45,
    obstacle_slow_distance=0.75,
    cruise_speed=0.18,
    slow_speed=0.08,
    turn_speed=0.75,
    lane_kp=0.9,
    max_angular_speed=1.2,
    speed_scale=1.0,
):
    mode = normalize_mode(mode)
    detection = str(detection or "").strip().lower().replace("-", "_").replace(" ", "_")
    manual_command = normalize_manual_command(manual_command)

    if emergency_stop or mode == "stop":
        return zero_motion()
    if mode in {"auto", "color_track", "object_follow", "mapping"} and not has_recent_scan:
        return zero_motion()
    if front_distance <= obstacle_stop_distance:
        return zero_motion()
    if mode == "navigation":
        return zero_motion()

    speed_scale = clamp(float(speed_scale), 0.0, 1.0)
    scaled_cruise_speed = cruise_speed * speed_scale
    scaled_slow_speed = slow_speed * speed_scale
    scaled_turn_speed = turn_speed * speed_scale
    speed = scaled_slow_speed if front_distance <= obstacle_slow_distance else scaled_cruise_speed

    if mode in {"manual", "mapping"}:
        if not has_recent_manual:
            return zero_motion()
        return _manual_motion(manual_command, speed, scaled_turn_speed)

    if mode == "color_track":
        if not has_recent_lane:
            return zero_motion()
        return _offset_follow_motion(lane_offset, scaled_slow_speed, lane_kp, max_angular_speed)

    if mode == "object_follow":
        if not has_recent_lane:
            return zero_motion()
        return _offset_follow_motion(lane_offset, scaled_slow_speed, lane_kp, max_angular_speed)

    if mode == "auto":
        if not has_recent_detection:
            return zero_motion()
        motion = _detection_motion(detection, scaled_cruise_speed, scaled_slow_speed, scaled_turn_speed)
        if motion is not None:
            return motion
        motion = zero_motion()
        motion["linear_x"] = speed
        if has_recent_lane:
            motion["angular_z"] = clamp(
                -float(lane_offset) * lane_kp,
                -max_angular_speed,
                max_angular_speed,
            )
        return motion

    return zero_motion()


def _manual_motion(command, speed, turn_speed):
    motion = zero_motion()
    if command == "forward":
        motion["linear_x"] = speed
    elif command == "backward":
        motion["linear_x"] = -speed
    elif command == "left":
        motion["linear_y"] = speed
    elif command == "right":
        motion["linear_y"] = -speed
    elif command in {"turn_l", "turn_left"}:
        motion["angular_z"] = turn_speed
    elif command in {"turn_r", "turn_right"}:
        motion["angular_z"] = -turn_speed
    return motion


def _detection_motion(detection, cruise_speed, slow_speed, turn_speed):
    motion = zero_motion()
    if detection in {"red_light", "shutdown", "stop"}:
        return motion
    if detection in {"turn_right", "right"}:
        motion["angular_z"] = -turn_speed
        return motion
    if detection in {"turn_left", "left"}:
        motion["angular_z"] = turn_speed
        return motion
    if detection in {"go_straight", "green_light", "no_light"}:
        motion["linear_x"] = cruise_speed
        return motion
    if detection in {"limiting_velocity", "school_decelerate", "slow", "person"}:
        motion["linear_x"] = slow_speed
        return motion
    return None


def _offset_follow_motion(lane_offset, speed, lane_kp, max_angular_speed):
    motion = zero_motion()
    motion["linear_x"] = speed
    motion["angular_z"] = clamp(
        -float(lane_offset) * lane_kp,
        -max_angular_speed,
        max_angular_speed,
    )
    return motion
