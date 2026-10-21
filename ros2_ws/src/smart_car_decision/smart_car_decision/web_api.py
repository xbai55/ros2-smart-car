"""车端（Jetson）Web API：把 Web 请求适配为现有 ROS2 控制意图与状态查询。

约束（与仓库文档一致）：

* 本模块只负责 ``HTTP / WebSocket -> ROS2 Topic`` 的适配，不做运动决策；
* 绝不发布 ``/cmd_vel``，速度仲裁始终由 ``decision_controller`` 完成；
* 不导入 ``rclpy``，因此可以在没有 ROS2 的机器上用 ``fastapi.testclient`` 直接测试。

ROS2 适配通过传入的 ``node`` 对象完成（鸭子类型）。``create_app(node)`` 需要：

发布 / 控制::

    set_mode(mode) -> str
    set_command(command) -> str
    set_emergency_stop(enabled) -> bool
    set_speed_scale(value) -> float
    set_color_config(payload) -> dict
    set_mode_obstacle_stop_distance(mode, distance) -> dict
    set_tracking_target(payload) -> dict
    set_patrol_task(payload) -> dict       # 可选
    set_mission_task(payload) -> dict      # 可选

状态读取::

    store.snapshot() -> dict
    map_snapshot.snapshot() -> dict | None            # GET /api/map
    pose_debug_log.snapshot(limit) / .clear()         # 调试接口
    mapping_restart.restart()                         # POST /api/mapping/restart
    ros_status_age_sec() -> float | None              # 可选，/health 与 network 字段
    get_logger()                                      # 可选，ROS2 日志
"""

from __future__ import annotations

import asyncio
import logging
import os
import time
from contextlib import nullcontext
from pathlib import Path
from typing import Any

from fastapi import Body, FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, Response, StreamingResponse
from fastapi.staticfiles import StaticFiles
from .mapping_settings import turn_speed, laser_range

from .control_policy import (
    MANUAL_COMMAND_MODES,
    VALID_MANUAL_COMMANDS,
    VALID_MODES,
)

SERVICE_NAME = "insightrover-vehicle-web-node"
SERVICE_VERSION = "0.1.0"

# /robot/status 的推送频率为 5 Hz，因此 3 秒未更新视为「延迟」，10 秒视为「断开」。
STATUS_FRESH_SEC = 3.0
STATUS_STALE_SEC = 10.0

STATUS_WS_PERIOD_SEC = 0.5

# 主机端 Robot Gateway 使用 rotate_left / rotate_right 表达原地转向，
# 车端 control_policy 使用的名字是 turn_left / turn_right，这里做一次别名映射。
MANUAL_COMMAND_ALIASES = {
    "rotate_left": "turn_left",
    "rotate_right": "turn_right",
    "left_turn": "turn_left",
    "right_turn": "turn_right",
}

# 控制意图名字 -> Web API 内部目标（主机端 Gateway 会用这些名字）
COMMAND_NAME_TARGETS = {
    "mode": "mode",
    "set_mode": "mode",
    "speed": "speed",
    "speed_scale": "speed",
    "set_speed": "speed",
    "emergency_stop": "emergency_stop",
    "estop": "emergency_stop",
    "patrol_task": "patrol_task",
    "mission_task": "mission_task",
}

# ROS2 控制意图 Topic -> Web API 内部目标（主机端 Gateway 也会直接给 topic）
TOPIC_TARGETS = {
    "/manual_cmd": "manual_cmd",
    "/robot/mode/set": "mode",
    "/robot/speed_scale": "speed",
    "/robot/emergency_stop/set": "emergency_stop",
    "/patrol_task/set": "patrol_task",
    "/mission_task/set": "mission_task",
}

# 安全红线：Web Node 不是最终速度控制器，任何请求都不允许指定 /cmd_vel。
FORBIDDEN_TOPICS = {"/cmd_vel"}

PATROL_ACTIONS = {"start", "resume", "pause", "cancel", "progress"}
MISSION_ACTIONS = {"dispatch", "transporting", "pickup", "handover", "complete", "cancel", "status"}

DOCUMENTED_STATUS_KEYS = (
    "status",
    "mode",
    "battery",
    "speed",
    "position",
    "network",
    "temperature",
    "current_task",
)

# 车端 ROS2 项目目前没有电池 / 温度话题，因此这两个字段固定为 null，
# 并通过 capabilities 明确告诉主机端「不支持」而不是「值是 0」。
FIELD_CAPABILITIES = {
    "battery": {"supported": False, "source": None, "reason": "ROS2 项目中无电池/电压话题"},
    "temperature": {"supported": False, "source": None, "reason": "ROS2 项目中无温度话题"},
    "position": {"supported": True, "source": "map_pose (TF map->base_link)", "reason": None},
    "speed": {"supported": True, "source": "odom.linear_speed", "reason": None},
    "current_task": {
        "supported": True,
        "source": "/patrol_task/progress, /mission_task/state",
        "reason": None,
    },
}


class WebRequestError(ValueError):
    """请求格式 / 取值错误，携带建议的 HTTP 状态码。"""

    def __init__(self, detail: str, status_code: int = 422):
        super().__init__(detail)
        self.detail = detail
        self.status_code = int(status_code)


def _normalize_token(value) -> str:
    return str(value or "").strip().lower().replace("-", "_").replace(" ", "_")


def _as_dict(value) -> dict:
    return value if isinstance(value, dict) else {}


def _payload_body(payload) -> tuple[dict, dict]:
    """拆出请求体与嵌套的 ``payload`` 字段（主机端 Gateway 的格式）。"""
    body = _as_dict(payload)
    inner = _as_dict(body.get("payload"))
    return body, inner


def _first_present(*candidates):
    for candidate in candidates:
        if candidate is not None:
            return candidate
    return None


def _as_float(value, field_name: str) -> float:
    try:
        return float(value)
    except (TypeError, ValueError) as exc:
        raise WebRequestError(f"{field_name} 必须是数字，收到 {value!r}") from exc


def _as_bool(value, field_name: str = "enabled") -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    token = _normalize_token(value)
    if token in {"true", "1", "on", "yes", "enable", "enabled"}:
        return True
    if token in {"false", "0", "off", "no", "disable", "disabled"}:
        return False
    raise WebRequestError(f"{field_name} 必须是布尔值，收到 {value!r}")


def normalize_manual_command_name(value) -> str:
    """把手动控制命令统一成 control_policy 认可的取值。"""
    token = _normalize_token(value)
    token = MANUAL_COMMAND_ALIASES.get(token, token)
    return token if token in VALID_MANUAL_COMMANDS else ""


def normalize_mode_name(value) -> str:
    """严格校验模式名；非法模式不会被静默降级为 stop。"""
    token = _normalize_token(value)
    if token not in VALID_MODES:
        raise WebRequestError(
            f"不支持的模式 {value!r}，可选：{', '.join(sorted(VALID_MODES))}"
        )
    return token


def normalize_command_request(payload) -> dict:
    """把「前端 / 主机端 Gateway」的多种请求格式统一成内部目标。

    返回 ``{"target": ..., "value": ...}``，其中 target 取值：

    ``manual_cmd`` / ``mode`` / ``speed`` / ``emergency_stop`` /
    ``patrol_task`` / ``mission_task``。
    """
    body, inner = _payload_body(payload)
    topic = str(_first_present(body.get("topic"), inner.get("topic")) or "").strip()
    if topic in FORBIDDEN_TOPICS:
        raise WebRequestError(f"Web Node 禁止发布 {topic}，速度由 decision_controller 仲裁", 403)

    name = _normalize_token(
        _first_present(body.get("command"), body.get("action"), inner.get("command"), inner.get("action"))
    )

    target = COMMAND_NAME_TARGETS.get(name) or TOPIC_TARGETS.get(topic) or "manual_cmd"

    if target == "mode":
        raw = _first_present(body.get("mode"), inner.get("mode"), body.get("value"), inner.get("value"))
        if raw is None:
            raise WebRequestError("缺少 mode 字段")
        return {"target": "mode", "value": normalize_mode_name(raw)}

    if target == "speed":
        raw = _first_present(
            body.get("scale"),
            body.get("speed_scale"),
            body.get("speed"),
            inner.get("scale"),
            inner.get("speed_scale"),
            inner.get("speed"),
        )
        if raw is None:
            raise WebRequestError("缺少 speed_scale 字段")
        return {"target": "speed", "value": _as_float(raw, "speed_scale")}

    if target == "emergency_stop":
        raw = _first_present(
            body.get("enabled"),
            body.get("emergency_stop"),
            inner.get("enabled"),
            inner.get("emergency_stop"),
        )
        if raw is None:
            raise WebRequestError("缺少 enabled 字段")
        return {"target": "emergency_stop", "value": _as_bool(raw)}

    if target in {"patrol_task", "mission_task"}:
        return {"target": target, "value": normalize_task_request(payload, target)}

    command = normalize_manual_command_name(name)
    if not command:
        raise WebRequestError(
            "不支持的控制指令 {!r}，可选：{}".format(
                name, ", ".join(sorted(VALID_MANUAL_COMMANDS))
            ),
            400,
        )
    return {"target": "manual_cmd", "value": command}


def normalize_task_request(payload, target: str) -> dict:
    """校验巡检 / 运输任务载荷（对应 /patrol_task/set、/mission_task/set）。"""
    if target not in {"patrol_task", "mission_task"}:
        raise WebRequestError(f"未知任务类型 {target!r}")
    task = dict(_unwrap(payload))
    action = _normalize_token(task.get("action"))
    allowed = PATROL_ACTIONS if target == "patrol_task" else MISSION_ACTIONS
    if action not in allowed:
        raise WebRequestError(
            f"{target} 需要 action 字段，可选：{', '.join(sorted(allowed))}"
        )
    task["action"] = action
    return task


def normalize_mode_request(payload) -> str:
    """POST /api/mode：兼容 ``{"mode": ...}`` 与 ``{"payload": {"mode": ...}}``。"""
    body, inner = _payload_body(payload)
    raw = _first_present(body.get("mode"), inner.get("mode"), body.get("value"), inner.get("value"))
    if raw is None:
        raise WebRequestError("缺少 mode 字段")
    return normalize_mode_name(raw)


def normalize_speed_request(payload) -> float:
    """POST /api/speed：兼容 ``{"scale": ...}``、``{"speed_scale": ...}``、``{"speed": ...}``。"""
    body, inner = _payload_body(payload)
    raw = _first_present(
        body.get("scale"),
        body.get("speed_scale"),
        body.get("speed"),
        inner.get("scale"),
        inner.get("speed_scale"),
        inner.get("speed"),
    )
    if raw is None:
        raise WebRequestError("缺少 speed_scale 字段")
    return _as_float(raw, "speed_scale")


def normalize_emergency_request(payload) -> bool:
    """POST /api/emergency-stop：兼容 ``{"enabled": ...}`` 与 Gateway 的 ``payload.enabled``。"""
    body, inner = _payload_body(payload)
    raw = _first_present(
        body.get("enabled"),
        body.get("emergency_stop"),
        inner.get("enabled"),
        inner.get("emergency_stop"),
    )
    if raw is None:
        raise WebRequestError("缺少 enabled 字段")
    return _as_bool(raw)


def derive_status(snapshot) -> str:
    if snapshot.get("emergency_stop"):
        return "emergency_stop"
    return "idle" if _normalize_token(snapshot.get("mode") or "stop") == "stop" else "running"


def derive_position(snapshot):
    pose = _as_dict(snapshot.get("map_pose"))
    if not pose.get("ok"):
        return None
    return {
        "x": round(float(pose.get("x") or 0.0), 4),
        "y": round(float(pose.get("y") or 0.0), 4),
        "yaw": round(float(pose.get("yaw") or 0.0), 4),
    }


def derive_speed(snapshot):
    odom = _as_dict(snapshot.get("odom"))
    if not odom.get("ok"):
        return None
    return round(float(odom.get("linear_speed") or 0.0), 4)


def derive_network(age_sec) -> str:
    if age_sec is None:
        return "unknown"
    age = float(age_sec)
    if age <= STATUS_FRESH_SEC:
        return "connected"
    if age <= STATUS_STALE_SEC:
        return "stale"
    return "disconnected"


def derive_current_task(snapshot):
    """由 /patrol_task/progress 与 /mission_task/state 推导当前任务。"""
    entries = []
    patrol = _as_dict(snapshot.get("patrol_task"))
    if patrol.get("active"):
        entries.append(
            (
                float(patrol.get("updated_at") or 0.0),
                {"type": "patrol_task", "action": patrol.get("action"), "progress": patrol.get("progress")},
            )
        )
    mission = _as_dict(snapshot.get("mission_task"))
    if mission.get("active"):
        entries.append(
            (
                float(mission.get("updated_at") or 0.0),
                {
                    "type": "mission_task",
                    "action": mission.get("action"),
                    "status": mission.get("status"),
                },
            )
        )
    if not entries:
        return None
    return max(entries, key=lambda item: item[0])[1]


def build_status_summary(payload) -> dict:
    return {key: payload.get(key) for key in DOCUMENTED_STATUS_KEYS}


def build_status_payload(snapshot, *, ros_status_age_sec=None, now=None) -> dict:
    """在原有状态快照上补充主机端文档要求的字段（不伪造硬件数据）。"""
    now = time.time() if now is None else float(now)
    payload = dict(snapshot)
    payload.setdefault("mapping", {"session_id": None, "state": "idle", "started_at": None, "error": None})
    payload["status"] = derive_status(snapshot)
    payload["battery"] = None
    payload["temperature"] = None
    payload["position"] = derive_position(snapshot)
    payload["speed"] = derive_speed(snapshot)
    payload["network"] = derive_network(ros_status_age_sec)
    payload["current_task"] = derive_current_task(snapshot)
    payload["ros2_status_age_sec"] = None if ros_status_age_sec is None else round(float(ros_status_age_sec), 3)
    payload["capabilities"] = FIELD_CAPABILITIES
    payload["server_time"] = round(now, 3)
    return payload


def build_ws_status_frame(snapshot, *, ros_status_age_sec=None, now=None) -> dict:
    """WebSocket 状态帧：保留原有快照字段（旧控制台），并附带文档要求的信封。"""
    now = time.time() if now is None else float(now)
    payload = build_status_payload(snapshot, ros_status_age_sec=ros_status_age_sec, now=now)
    frame = dict(payload)
    frame["type"] = "robot_status"
    frame["timestamp"] = round(now, 3)
    frame["data"] = build_status_summary(payload)
    return frame


def build_health_payload(node, *, now=None) -> dict:
    """GET /health：Web Node 自身存活即返回 200，ROS2 数据情况放在 ros2 子字段。"""
    now = time.time() if now is None else float(now)
    age = ros_status_age_sec(node)
    return {
        "status": "ok",
        "service": SERVICE_NAME,
        "version": SERVICE_VERSION,
        "timestamp": round(now, 3),
        "node": node_name(node),
        "ros2": {
            "available": ros2_available(node),
            "data_ok": age is not None and age <= STATUS_FRESH_SEC,
            "data_age_sec": None if age is None else round(float(age), 3),
            "status": derive_network(age),
        },
        "endpoints": [
            "GET /health",
            "GET /api/status",
            "GET /api/map",
            "GET /api/video",
            "POST /api/command",
            "POST /api/mode",
            "POST /api/emergency-stop",
            "POST /api/speed",
            "POST /api/patrol-task",
            "POST /api/mission-task",
            "WS /ws/status",
            "WS /ws/control",
        ],
    }


def node_name(node) -> str:
    getter = getattr(node, "get_name", None)
    if callable(getter):
        try:
            return str(getter())
        except Exception:
            return "web_app_node"
    return "web_app_node"


def ros2_available(node) -> bool:
    flag = getattr(node, "ros2_available", None)
    return True if flag is None else bool(flag)


def ros_status_age_sec(node):
    getter = getattr(node, "ros_status_age_sec", None)
    if not callable(getter):
        return None
    try:
        age = getter()
    except Exception:
        return None
    return None if age is None else float(age)


def resolve_bind_address(host_parameter, port_parameter, environ=None) -> tuple[str, int]:
    """WEB_HOST / WEB_PORT 环境变量优先，其次 ROS2 参数，最后默认 0.0.0.0:8080。"""
    environ = os.environ if environ is None else environ
    host = str(environ.get("WEB_HOST") or host_parameter or "0.0.0.0").strip() or "0.0.0.0"
    raw_port = environ.get("WEB_PORT") or port_parameter or 8080
    try:
        port = int(raw_port)
    except (TypeError, ValueError):
        port = 8080
    if not 0 < port < 65536:
        port = 8080
    return host, port


def _logger(node):
    getter = getattr(node, "get_logger", None)
    if callable(getter):
        try:
            return getter()
        except Exception:
            pass
    return logging.getLogger(SERVICE_NAME)


def log_message(node, level: str, message: str) -> None:
    logger = _logger(node)
    # rclpy associates severity with the caller's source line. Keep each level
    # on its own line so a warning after an info message cannot break control.
    if level == "warning":
        logger.warning(message)
    elif level == "error":
        logger.error(message)
    elif level == "debug":
        logger.debug(message)
    elif level == "fatal":
        logger.fatal(message)
    else:
        logger.info(message)


def _unwrap(payload) -> dict:
    body = _as_dict(payload)
    inner = _as_dict(body.get("payload"))
    return inner or body


def _node_call(node, method_name: str, *args, **kwargs) -> Any:
    method = getattr(node, method_name, None)
    if not callable(method):
        raise HTTPException(status_code=501, detail=f"Web Node 未实现 {method_name}")
    return method(*args, **kwargs)


def create_app(
    node,
    *,
    camera=None,
    annotated_stream=None,
    static_dir=None,
    status_period_sec=STATUS_WS_PERIOD_SEC,
):
    """构造车端 FastAPI 应用（不依赖 ROS2，便于测试）。"""
    app = FastAPI(title="InsightRover 车端 Web Node", version=SERVICE_VERSION)
    static_path = Path(static_dir) if static_dir else None

    if static_path is not None and static_path.is_dir():
        app.mount("/app", StaticFiles(directory=str(static_path), html=True), name="app")
        assets_dir = static_path / "assets"
        if assets_dir.is_dir():
            app.mount("/assets", StaticFiles(directory=str(assets_dir)), name="assets")

    @app.middleware("http")
    async def log_requests(request, call_next):
        started = time.perf_counter()
        response = await call_next(request)
        elapsed_ms = (time.perf_counter() - started) * 1000.0
        log_message(
            node,
            "info",
            f"HTTP {request.method} {request.url.path} -> {response.status_code} ({elapsed_ms:.1f} ms)",
        )
        return response

    def _reject(exc: WebRequestError) -> HTTPException:
        log_message(node, "warning", f"拒绝请求：{exc.detail}")
        return HTTPException(status_code=exc.status_code, detail=exc.detail)

    @app.get("/")
    def root():
        if static_path is None or not (static_path / "index.html").is_file():
            raise HTTPException(status_code=404, detail="web console is not installed")
        return FileResponse(static_path / "index.html")

    @app.get("/health")
    def health():
        return build_health_payload(node)

    @app.get("/api/status")
    def status():
        return build_status_payload(navigation_status_snapshot(), ros_status_age_sec=ros_status_age_sec(node))

    def navigation_status_snapshot():
        snapshot = node.store.snapshot()
        settings = getattr(node, "motion_settings", None)
        if settings is not None:
            snapshot["motion_settings"] = settings.snapshot()
        mapping = getattr(node, "mapping_restart", None)
        if mapping is not None and callable(getattr(mapping, "snapshot", None)):
            snapshot["mapping"] = mapping.snapshot()
        bridge = getattr(node, "navigation", None)
        snapshot["navigation"] = bridge.snapshot() if bridge else {
            "ready": False, "state": "idle", "message": "车端 Nav2 尚未安装或启动",
            "goal_id": None, "goal": None, "path": [], "distance_remaining": None,
            "estimated_time_remaining": None,
        }
        return snapshot

    def navigation_component(name):
        value = getattr(node, name, None)
        if value is None:
            raise HTTPException(status_code=503, detail="车端导航服务不可用，请更新车端并安装 Nav2")
        return value

    def navigation_error(exc):
        code = 504 if isinstance(exc, TimeoutError) else 409 if isinstance(exc, RuntimeError) else 422
        return HTTPException(status_code=code, detail=str(exc))

    @app.get("/api/navigation/status")
    def navigation_status():
        return navigation_status_snapshot()["navigation"]

    @app.get('/api/safety/status')
    def safety_status():
        worker = getattr(node, 'safety_vision', None)
        return worker.snapshot() if worker else {'state': 'unavailable', 'message': '车端巡检识别未启动', 'detections': []}

    @app.get('/api/safety/events')
    def safety_events():
        worker = getattr(node, 'safety_vision', None)
        if not worker:
            raise HTTPException(503, '车端巡检识别未启动')
        return {'events': worker.outbox.pending()}

    @app.get('/api/safety/corridors')
    def safety_corridors():
        worker = getattr(node, 'safety_vision', None)
        return {'corridors': worker.corridors() if worker else []}

    @app.post('/api/safety/corridors')
    def configure_safety_corridors(payload: dict = Body(...)):
        from .navigation_config import map_key, drawing_identity
        worker = getattr(node, 'safety_vision', None)
        runner = getattr(node, 'navigation_tasks', None)
        if not worker:
            raise HTTPException(503, '车端巡检识别未启动')
        if node.store.snapshot().get('mode') != 'stop' or runner and runner.active:
            raise HTTPException(409, '请在停止且无执行任务时配置通道')
        grid = node.map_snapshot.snapshot()
        if not grid or payload.get('map_key') != map_key(grid) or payload.get('control_session_id') != grid.get('session_id'):
            raise HTTPException(409, '地图或控制会话已变化，请刷新后重试')
        calibration = node.navigation_config.snapshot().get('calibration') if getattr(node, 'navigation_config', None) else None
        if not calibration or calibration.get('invalidated') or payload.get('calibration_matrix') != calibration['matrix'] or drawing_identity(payload.get('calibration_drawing')) != drawing_identity(calibration.get('drawing')):
            raise HTTPException(409, '平面图对齐已变化，请刷新后重试')
        zones = payload.get('corridors')
        if not isinstance(zones, list) or any(z.get('map_key') != map_key(grid) for z in zones if isinstance(z, dict)):
            raise HTTPException(422, '通道必须绑定当前地图')
        try:
            previous = [z for z in worker.corridors() if z.get('map_key') != map_key(grid)]
            return {'corridors': worker.configure_corridors(previous + zones)}
        except (ValueError, KeyError, TypeError) as exc:
            raise HTTPException(422, str(exc)) from exc
        except (RuntimeError, OSError) as exc:
            raise HTTPException(409, str(exc)) from exc

    @app.post('/api/safety/events/ack')
    def acknowledge_safety_events(payload: dict = Body(...)):
        worker = getattr(node, 'safety_vision', None)
        if not worker:
            raise HTTPException(503, '车端巡检识别未启动')
        try:
            worker.outbox.acknowledge(payload.get('event_ids'))
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from exc
        return {'ok': True}

    @app.get("/api/navigation/config")
    def navigation_config():
        return navigation_component("navigation_config").snapshot()

    @app.get("/api/navigation/runtime")
    def navigation_runtime():
        return navigation_component("navigation_runtime").snapshot()

    @app.post("/api/navigation/load-map")
    def load_navigation_map(payload: dict = Body(...)):
        try:
            return navigation_component("navigation_runtime").load(payload)
        except (ValueError, TypeError, KeyError, RuntimeError, OSError) as exc:
            raise navigation_error(exc) from exc

    @app.post("/api/navigation/initial-pose")
    def initial_navigation_pose(payload: dict = Body(...)):
        try:
            return navigation_component("navigation_runtime").seed(payload)
        except (ValueError, TypeError, KeyError, RuntimeError) as exc:
            raise navigation_error(exc) from exc

    @app.get("/api/navigation/task")
    def navigation_task(run_id: str | None = None):
        try:
            return navigation_component("navigation_tasks").snapshot_for(run_id)
        except ValueError as exc:
            raise navigation_error(exc) from exc

    @app.post("/api/navigation/task")
    async def create_navigation_task(payload: dict = Body(...)):
        try:
            return await navigation_component("navigation_tasks").create(payload)
        except (ValueError, TypeError, KeyError, RuntimeError) as exc:
            raise navigation_error(exc) from exc

    @app.post("/api/navigation/task/action")
    async def action_navigation_task(payload: dict = Body(...)):
        try:
            return await navigation_component("navigation_tasks").action(payload)
        except (ValueError, TypeError, KeyError, RuntimeError) as exc:
            raise navigation_error(exc) from exc

    @app.post("/api/navigation/calibration")
    def navigation_calibration(payload: dict = Body(...)):
        from .navigation_config import map_key
        bridge = getattr(node, "navigation", None)
        runner = getattr(node, "navigation_tasks", None)
        if runner and runner.active:
            raise HTTPException(status_code=409, detail="请先取消运输或巡航任务再修改标定")
        with getattr(bridge, "lock", nullcontext()):
            if bridge and bridge.snapshot()["state"] in {"starting", "running"}:
                raise HTTPException(status_code=409, detail="请先停止导航再对齐地图")
            snapshot = node.map_snapshot.snapshot()
            if snapshot is None or payload.get("map_key") != map_key(snapshot):
                raise HTTPException(status_code=409, detail="地图已变化，请重新选择对应位置")
            try:
                result = navigation_component("navigation_config").calibrate(payload.get("anchors"), snapshot, payload.get("drawing"))
                refresh = getattr(node, "refresh_navigation_map", None)
                if callable(refresh):
                    refresh()
                return result
            except (ValueError, TypeError, KeyError) as exc:
                raise navigation_error(exc) from exc

    @app.post("/api/navigation/places")
    def add_navigation_place(payload: dict = Body(...)):
        try:
            maps = getattr(node, "navigation_map", node.map_snapshot)
            return navigation_component("navigation_config").add_place(payload, maps.snapshot(), getattr(node, "navigation_radius", .25))
        except (ValueError, TypeError, KeyError) as exc:
            raise navigation_error(exc) from exc

    @app.delete("/api/navigation/places/{place_id}")
    def remove_navigation_place(place_id: str):
        try:
            return navigation_component("navigation_config").remove_place(place_id)
        except ValueError as exc:
            raise navigation_error(exc) from exc

    @app.post("/api/navigation/plan")
    async def navigation_plan(payload: dict = Body(...)):
        try:
            runner = getattr(node, "navigation_tasks", None)
            if runner and runner.active:
                raise RuntimeError("已有运输或巡航任务，请先暂停或取消任务")
            return await navigation_component("navigation").plan(payload)
        except (ValueError, TypeError, KeyError, RuntimeError, TimeoutError) as exc:
            raise navigation_error(exc) from exc

    @app.post("/api/navigation/start")
    async def navigation_start(payload: dict = Body(...)):
        try:
            runner = getattr(node, "navigation_tasks", None)
            if runner and runner.active:
                raise RuntimeError("已有运输或巡航任务，请先取消任务")
            return await navigation_component("navigation").start(payload)
        except (ValueError, TypeError, KeyError, RuntimeError, TimeoutError) as exc:
            raise navigation_error(exc) from exc

    @app.post("/api/navigation/cancel")
    async def navigation_cancel():
        runner = getattr(node, "navigation_tasks", None)
        if runner:
            runner.interrupt()
        bridge = getattr(node, "navigation", None)
        if bridge:
            return bridge.cancel()
        _node_call(node, "set_mode", "stop")
        return {"ok": True, "message": "小车已停止"}

    @app.get("/api/map")
    def map_snapshot():
        snapshot = node.map_snapshot.snapshot()
        if snapshot is None:
            raise HTTPException(status_code=404, detail="map is not available")
        mapping = getattr(node, "mapping_restart", None)
        if mapping is not None and callable(getattr(mapping, "snapshot", None)):
            session = mapping.snapshot()
            if snapshot.get("session_id") != session.get("session_id"):
                raise HTTPException(status_code=404, detail="waiting for current mapping session")
        return snapshot

    @app.get("/api/video")
    def video_info(frame: bool = False):
        if frame:
            if camera is None:
                raise HTTPException(status_code=503, detail="camera is not available")
            blocked = bool(camera.is_blocked_by_mode())
            if blocked:
                camera.close()
            source = annotated_stream if blocked else camera
            snapshot = source.frame_snapshot() if source is not None else None
            if snapshot is None:
                raise HTTPException(status_code=503, detail="waiting for a fresh camera frame")
            return Response(content=snapshot["jpeg"], media_type="image/jpeg", headers={
                "Cache-Control": "no-store, no-cache, must-revalidate",
                "X-Accel-Buffering": "no",
                "X-Frame-Sequence": str(snapshot["sequence"]),
                "X-Frame-Age-Ms": str(snapshot["age_ms"]),
                "X-Frame-Source": "annotated" if blocked else "camera",
            })
        if camera is None:
            return {
                "ok": False,
                "stream_url": None,
                "message": "camera is not available",
            }
        blocked = bool(camera.is_blocked_by_mode())
        info = {
            "ok": True,
            "stream_url": "/video_feed",
            "stream_type": "multipart/x-mixed-replace",
            "source": "annotated" if blocked else "camera",
            "blocked_by_mode": blocked,
        }
        info["frame_url"] = "/api/video?frame=true"
        if callable(getattr(camera, "diagnostics", None)):
            info["capture"] = camera.diagnostics()
        return info

    @app.get("/api/debug/pose-log")
    def pose_log(limit: int = 600):
        return node.pose_debug_log.snapshot(limit=limit)

    @app.post("/api/debug/pose-log/clear")
    def clear_pose_log():
        node.pose_debug_log.clear()
        return {"ok": True, "message": "pose debug log cleared"}

    @app.post("/api/mapping/settings")
    def update_motion_settings(payload: dict | None = Body(default=None)):
        changes = payload or {}
        if not changes or set(changes) - {"turn_speed", "max_laser_range"}:
            raise HTTPException(status_code=422, detail="无效的运动或建图设置")
        try:
            validated = {key: (turn_speed(value) if key == "turn_speed" else laser_range(value))
                         for key, value in changes.items()}
            settings = _node_call(node, "set_motion_settings", validated)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        except OSError as exc:
            raise HTTPException(status_code=500, detail="设置保存失败，请查看车端日志") from exc
        log_message(node, "info", f"运动与建图设置 -> {settings}")
        return {"ok": True, "settings": settings}

    @app.post("/api/mapping/restart")
    def restart_mapping():
        runner = getattr(node, "navigation_tasks", None)
        if runner and runner.active:
            raise HTTPException(status_code=409, detail="请先取消运输或巡航任务再建图")
        runtime = getattr(node, "navigation_runtime", None)
        snapshot = node.store.snapshot()
        blocked = [name for name in ("lidar", "odom", "tf") if not _as_dict(snapshot.get(name)).get("ok")]
        if blocked:
            raise HTTPException(
                status_code=409,
                detail=f"mapping restart blocked by unhealthy: {','.join(blocked)}",
            )
        try:
            bridge = getattr(node, "navigation", None)
            with getattr(runtime, "operation_lock", nullcontext()), getattr(bridge, "lock", nullcontext()):
                if runner and runner.active:
                    raise HTTPException(status_code=409, detail="请先取消运输或巡航任务再建图")
                _node_call(node, "set_command", "stop")
                if bridge and bridge.snapshot()["state"] in {"starting", "running"}:
                    bridge.cancel("切换建图，停止导航")
                _node_call(node, "set_mode", "stop")
                if runtime and runtime.snapshot().get("digest"):
                    runtime.stop()
                _node_call(node, "set_mode", "mapping")
                config = getattr(node, "navigation_config", None)
                if config is not None:
                    config.invalidate_calibration()
                try:
                    return node.mapping_restart.restart()
                finally:
                    # Refresh once after the store is cleared. Failed startup must
                    # also retain invalidation rather than revive an old alignment.
                    refresh = getattr(node, "refresh_navigation_map", None)
                    if callable(refresh):
                        refresh()
        except RuntimeError as exc:
            raise HTTPException(status_code=500, detail=str(exc)) from exc

    @app.post("/api/mapping/save")
    def save_mapping(payload: dict | None = Body(default=None)):
        try:
            if payload and payload.get("include_snapshot") is True:
                return node.map_snapshot.save(include_snapshot=True)
            return node.map_snapshot.save()
        except RuntimeError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @app.post("/api/command")
    async def command(payload: dict | None = Body(default=None)):
        try:
            request = normalize_command_request(payload or {})
        except WebRequestError as exc:
            raise _reject(exc) from exc
        return apply_control_request(node, request)

    @app.post("/api/mode")
    async def mode(payload: dict | None = Body(default=None)):
        try:
            requested = normalize_mode_request(payload or {})
        except WebRequestError as exc:
            raise _reject(exc) from exc
        return apply_control_request(node, {"target": "mode", "value": requested})

    @app.post("/api/emergency-stop")
    async def emergency_stop(payload: dict | None = Body(default=None)):
        try:
            enabled = normalize_emergency_request(payload or {})
        except WebRequestError as exc:
            raise _reject(exc) from exc
        return apply_control_request(node, {"target": "emergency_stop", "value": enabled})

    @app.post("/api/speed")
    async def speed(payload: dict | None = Body(default=None)):
        try:
            requested = normalize_speed_request(payload or {})
        except WebRequestError as exc:
            raise _reject(exc) from exc
        scale = _node_call(node, "set_speed_scale", requested)
        log_message(node, "info", f"速度比例请求 -> {scale}")
        return {"ok": True, "target": "speed_scale", "speed_scale": scale}

    @app.post("/api/patrol-task")
    async def patrol_task(payload: dict | None = Body(default=None)):
        try:
            request = normalize_task_request(payload, "patrol_task")
        except WebRequestError as exc:
            raise _reject(exc) from exc
        task = _node_call(node, "set_patrol_task", request)
        log_message(node, "info", f"巡检任务请求 -> {task}")
        return {"ok": True, "target": "patrol_task", "patrol_task": task}

    @app.post("/api/mission-task")
    async def mission_task(payload: dict | None = Body(default=None)):
        try:
            request = normalize_task_request(payload, "mission_task")
        except WebRequestError as exc:
            raise _reject(exc) from exc
        task = _node_call(node, "set_mission_task", request)
        log_message(node, "info", f"运输任务请求 -> {task}")
        return {"ok": True, "target": "mission_task", "mission_task": task}

    @app.post("/api/color-target")
    async def color_target(payload: dict | None = Body(default=None)):
        config = _node_call(node, "set_color_config", _unwrap(payload))
        log_message(node, "info", f"颜色配置请求 -> {config.get('name')}")
        return {"color_config": config}

    @app.post("/api/mode-obstacle-stop-distance")
    async def mode_obstacle_stop_distance(payload: dict | None = Body(default=None)):
        body = _unwrap(payload)
        try:
            target_mode = normalize_mode_name(body.get("mode"))
            distance = _as_float(body.get("distance"), "distance")
        except WebRequestError as exc:
            raise _reject(exc) from exc
        distances = _node_call(node, "set_mode_obstacle_stop_distance", target_mode, distance)
        return {"mode_obstacle_stop_distances": distances}

    @app.post("/api/tracking-target")
    async def tracking_target(payload: dict | None = Body(default=None)):
        try:
            request = _node_call(node, "set_tracking_target", _unwrap(payload))
        except (TypeError, ValueError) as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        return {"tracking_target": request}

    @app.get("/video_feed")
    def video_feed():
        if camera is None:
            raise HTTPException(status_code=503, detail="camera is not available")
        if camera.is_blocked_by_mode():
            camera.close()
            return StreamingResponse(
                annotated_stream.frames(),
                media_type="multipart/x-mixed-replace; boundary=frame",
                headers={"Cache-Control": "no-store", "X-Accel-Buffering": "no"},
            )
        if not camera.open():
            raise HTTPException(status_code=503, detail="camera is not available")
        return StreamingResponse(
            camera.frames(),
            media_type="multipart/x-mixed-replace; boundary=frame",
            headers={"Cache-Control": "no-store", "X-Accel-Buffering": "no"},
        )

    @app.websocket("/ws/status")
    async def websocket_status(websocket: WebSocket):
        await websocket.accept()
        log_message(node, "info", "WebSocket /ws/status 已连接")
        try:
            while True:
                frame = build_ws_status_frame(
                    navigation_status_snapshot(),
                    ros_status_age_sec=ros_status_age_sec(node),
                )
                await websocket.send_json(frame)
                await asyncio.sleep(float(status_period_sec))
        except WebSocketDisconnect:
            log_message(node, "info", "WebSocket /ws/status 已断开")
            return
        except Exception as exc:  # 客户端异常不应导致 ROS2 节点退出
            log_message(node, "warning", f"WebSocket /ws/status 关闭：{exc}")
            return

    @app.websocket("/ws/control")
    async def websocket_control(websocket: WebSocket):
        await websocket.accept()
        log_message(node, "info", "WebSocket /ws/control 已连接")
        try:
            while True:
                payload = await websocket.receive_json()
                try:
                    request = normalize_command_request(payload)
                except WebRequestError as exc:
                    log_message(node, "warning", f"拒绝 WebSocket 控制请求：{exc.detail}")
                    await websocket.send_json({"ok": False, "detail": exc.detail})
                    continue
                try:
                    result = apply_control_request(node, request)
                    await websocket.send_json({"ok": result["ok"], "command": result.get("command", request["value"])})
                except HTTPException as exc:
                    await websocket.send_json({"ok": False, "detail": exc.detail})
        except WebSocketDisconnect:
            log_message(node, "info", "WebSocket /ws/control 已断开")
            _node_call(node, "set_command", "stop")

    return app


def apply_control_request(node, request: dict) -> dict:
    """把归一化后的控制请求发布到对应的 ROS2 控制意图话题。"""
    target = request["target"]
    value = request["value"]

    if target == "manual_cmd":
        runner = getattr(node, "navigation_tasks", None)
        if value == "stop" and runner:
            runner.interrupt("停止指令已取消任务")
        bridge = getattr(node, "navigation", None)
        if value == "stop" and bridge and bridge.snapshot()["state"] in {"starting", "running"}:
            bridge.cancel("停止指令已取消导航")
        result = _node_call(node, "set_command", value)
        if value != "stop" and result == "stop":
            log_message(node, "warning", f"手动命令 {value} 被拒绝：当前模式不允许手动控制")
            raise HTTPException(status_code=409, detail="manual commands require manual or mapping mode")
        log_message(node, "info", f"手动命令请求 -> {result}")
        return {"ok": True, "target": "manual_cmd", "command": result}

    if target == "mode":
        recorder = getattr(node, "mapping_recorder", None)
        if value == "mapping" and recorder and recorder.snapshot()["state"] != "recording":
            raise HTTPException(status_code=409, detail="请通过开始建图入口创建带完整输入记录的建图会话")
        runtime = getattr(node, "navigation_runtime", None)
        if value == "mapping" and runtime and runtime.snapshot().get("digest"):
            raise HTTPException(status_code=409, detail="请使用开始建图入口切换，以结束当前导航定位")
        runner = getattr(node, "navigation_tasks", None)
        if runner and value != "navigation":
            runner.interrupt("模式切换已取消任务")
        bridge = getattr(node, "navigation", None)
        if bridge and value != "navigation" and bridge.snapshot()["state"] in {"starting", "running"}:
            bridge.cancel("模式已切换，导航已停止")
        mode_name = _node_call(node, "set_mode", value)
        if mode_name != value:
            raise HTTPException(status_code=409, detail="release emergency stop before changing mode")
        log_message(node, "info", f"模式切换请求 -> {mode_name}")
        return {"ok": True, "target": "mode", "mode": mode_name}

    if target == "speed":
        scale = _node_call(node, "set_speed_scale", value)
        log_message(node, "info", f"速度比例请求 -> {scale}")
        return {"ok": True, "target": "speed_scale", "speed_scale": scale}

    if target == "emergency_stop":
        runner = getattr(node, "navigation_tasks", None)
        if value and runner:
            runner.interrupt("急停已取消任务，请核对现场后重新创建")
        state = _node_call(node, "set_emergency_stop", value)
        log_message(node, "warning" if state else "info", f"急停请求 -> enabled={state}")
        return {"ok": True, "target": "emergency_stop", "emergency_stop": state}

    if target == "patrol_task":
        task = _node_call(node, "set_patrol_task", value)
        log_message(node, "info", f"巡检任务请求 -> {task}")
        return {"ok": True, "target": "patrol_task", "patrol_task": task}

    if target == "mission_task":
        task = _node_call(node, "set_mission_task", value)
        log_message(node, "info", f"运输任务请求 -> {task}")
        return {"ok": True, "target": "mission_task", "mission_task": task}

    raise HTTPException(status_code=400, detail=f"未知控制目标 {target}")
