"""Robot Gateway 契约定义。

所有消息使用 JSON，字段命名保持 snake_case。禁止任何消息直接发布 /cmd_vel。
"""

ALLOWED_TOPICS = [
    "/robot/mode/set",
    "/manual_cmd",
    "/robot/emergency_stop/set",
    "/robot/speed_scale",
    "/patrol_task/set",
    "/mission_task/set",
]

FORBIDDEN_TOPICS = ["/cmd_vel"]

ROBOT_STATUS_SCHEMA = {
    "$schema": "http://json-schema.org/draft-07/schema#",
    "title": "RobotStatus",
    "type": "object",
    "required": ["robot_id", "timestamp", "status", "mode"],
    "properties": {
        "robot_id": {"type": "string"},
        "timestamp": {"type": "string", "format": "date-time"},
        "status": {"enum": ["online", "degraded", "offline", "estop"]},
        "mode": {"type": "string"},
        "emergency_stop": {"type": "boolean"},
        "battery": {"type": "number"},
        "pose": {
            "type": "object",
            "properties": {
                "x": {"type": "number"},
                "y": {"type": "number"},
                "yaw": {"type": "number"},
            },
        },
        "health": {"type": "object"},
    },
}

COMMAND_SCHEMA = {
    "$schema": "http://json-schema.org/draft-07/schema#",
    "title": "RobotCommand",
    "type": "object",
    "required": ["command_id", "type", "topic"],
    "properties": {
        "command_id": {"type": "string"},
        "type": {"enum": ["mode", "manual_cmd", "emergency_stop", "speed_scale", "task"]},
        "topic": {"enum": ALLOWED_TOPICS},
        "payload": {"type": "object"},
    },
}