"""Robot Gateway（服务器端抽象）。

FastAPI 业务层只表达“控制意图”，由 Gateway 决定如何转发给车端 Web 节点，
保证业务代码与机器人通信方式解耦。对应契约见 robot-gateway/gateway/contracts.py：
Gateway 永不直接发布 /cmd_vel，只允许模式、手动命令、急停、速度比例和任务指令。

本阶段只做服务器端实现：车端 Web 服务地址来自配置（ROBOT_WEB_URL / app_settings.robot_web_url）。
地址为空或车端不可达时，返回结构化的“未下发”结果，不抛异常，便于前端展示与后续重试。
"""
from __future__ import annotations

from typing import Any
import time

from ..core.diagnostic_context import wire_headers
from ..services.diagnostics import emit

import httpx

from ..core.config import settings
from ..services.windows_credentials import machine_token

FORBIDDEN_TOPICS = ["/cmd_vel"]

# 手动控制命令 -> ROS2 话题
COMMAND_TOPICS: dict[str, str] = {
    "forward": "/manual_cmd",
    "backward": "/manual_cmd",
    "left": "/manual_cmd",
    "right": "/manual_cmd",
    "rotate_left": "/manual_cmd",
    "rotate_right": "/manual_cmd",
    "stop": "/manual_cmd",
    "set_mode": "/robot/mode/set",
    "speed_scale": "/robot/speed_scale",
    "emergency_stop": "/robot/emergency_stop/set",
    "patrol_task": "/patrol_task/set",
    "mission_task": "/mission_task/set",
}

ALLOWED_COMMANDS = set(COMMAND_TOPICS)


class RobotGateway:
    def __init__(self, base_url: str | None = None, timeout: float | None = None) -> None:
        self.base_url = (base_url if base_url is not None else settings.robot_web_url).rstrip("/")
        self.timeout = timeout or settings.robot_gateway_timeout

    @property
    def mode(self) -> str:
        return "http" if self.base_url else "offline"

    @staticmethod
    def _client(timeout: float) -> httpx.AsyncClient:
        # trust_env=False：车端在局域网内，不走系统 HTTP/SOCKS 代理
        headers = wire_headers()
        if token := machine_token():
            headers["X-InsightRover-Service-Token"] = token
        async def start(request):
            request.extensions['diagnostic_started'] = time.monotonic()

        async def finish(response):
            request = response.request
            if response.status_code < 400 and (request.method == 'GET' or request.url.path in {
                '/api/command', '/api/control-lease',
            }):
                return
            emit('gateway.response', f'http_{response.status_code}', module='robot_gateway',
                 level='WARN' if response.status_code >= 400 else 'INFO', details={
                     'status_code': response.status_code,
                     'elapsed_ms': (time.monotonic() - request.extensions['diagnostic_started']) * 1000,
                 })

        return httpx.AsyncClient(timeout=timeout, trust_env=False, headers=headers,
                                 event_hooks={'request': [start], 'response': [finish]})

    def _url(self, path: str) -> str:
        return f"{self.base_url}{path}"

    async def control_lease(self, payload=None):
        if not self.base_url:
            raise RuntimeError("未配置车端地址")
        async with self._client(1.5) as client:
            response = await (client.get(self._url("/api/control-lease")) if payload is None
                              else client.post(self._url("/api/control-lease"), json=payload))
            response.raise_for_status()
            return response.json()

    async def stop(self):
        if not self.base_url:
            raise RuntimeError("未配置车端地址")
        try:
            async with self._client(3) as client:
                response = await client.post(self._url("/api/stop"), json={})
                response.raise_for_status()
                value = response.json()
        except (httpx.HTTPError, ValueError) as exc:
            emit('gateway.failed', 'stop_response_unavailable', module='robot_gateway', level='ERROR', exception=exc)
            raise
        emit('gateway.stop', 'vehicle_stop_response', module='robot_gateway',
             details={key: value.get(key) for key in ('request_sent', 'controller_confirmed', 'stationary_confirmed')}
             if isinstance(value, dict) else {})
        return value

    async def operator_request(self, path, payload):
        if not self.base_url or path not in {"command", "mode", "mapping/restart"}:
            raise RuntimeError("车端操作不可用")
        timeout = 45 if path == "mapping/restart" else 2
        async with self._client(timeout) as client:
            response = await client.post(self._url("/api/" + path), json=payload)
            response.raise_for_status()
            return response.json()

    async def search_request(self, run_id, *, operation=None, payload=None):
        if not self.base_url:
            raise RuntimeError("未配置车端地址")
        if operation not in {None, "start", "action"}:
            raise ValueError("不支持的搜索接口")
        async with self._client(19 if operation == "start" else 3) as client:
            if operation is None:
                response = await client.get(self._url("/api/search"), params={"run_id": run_id})
                if response.status_code == 404:
                    return None
            else:
                response = await client.post(self._url("/api/search/" + operation),
                                             json={**payload, "run_id": run_id})
            response.raise_for_status()
            value = response.json()
            if (not isinstance(value, dict) or value.get("run_id") != run_id
                    or not isinstance(value.get("state"), str)):
                raise RuntimeError("搜索回执标识不匹配")
            return value

    async def save_slam_map(self) -> dict:
        if not self.base_url:
            raise RuntimeError("未配置小车地址，无法保存 SLAM 地图")
        async with self._client(max(self.timeout, 20.0)) as client:
            response = await client.post(self._url("/api/mapping/save"), json={"include_snapshot": True})
            response.raise_for_status()
            result = response.json()
        if not result.get("ok") or not isinstance(result.get("snapshot"), dict):
            raise RuntimeError("车端未返回地图快照，请更新车端；文件可能已保存在小车，但尚未登记到地图管理")
        return result

    async def navigation_request(self, path: str, payload: dict | None = None, *, query: dict | None = None) -> dict:
        if path not in {"load-map", "runtime", "task", "task/action", "resolve-resources", "config", "start"}:
            raise ValueError("不支持的导航接口")
        if not self.base_url:
            raise RuntimeError("未配置小车地址")
        async with self._client(max(self.timeout, 25.0)) as client:
            url = self._url(f"/api/navigation/{path}")
            response = await (client.get(url, params=query) if payload is None else client.post(url, json=payload))
            response.raise_for_status()
            return response.json()

    def build_command(
        self,
        robot_id: str,
        command: str,
        *,
        speed: float | None = None,
        params: dict[str, Any] | None = None,
        robot_code: str | None = None,
    ) -> dict[str, Any]:
        """把业务控制意图转换为车端可理解的命令结构（不真正发送）。"""
        topic = COMMAND_TOPICS[command]
        if topic in FORBIDDEN_TOPICS:
            raise ValueError(f"禁止直接发布 {topic}")
        payload: dict[str, Any] = dict(params or {})
        if speed is not None:
            payload["speed"] = speed
        if command == "set_mode":
            payload.setdefault("mode", payload.get("mode", "manual"))
        return {
            "robot_id": robot_code or robot_id,
            "type": "mode" if topic == "/robot/mode/set" else "manual_cmd",
            "topic": topic,
            "command": command,
            "payload": payload,
        }

    async def get_status(self, robot_id: str, *, robot_code: str | None = None) -> dict[str, Any]:
        if not self.base_url:
            return {
                "ok": False,
                "gateway": self.mode,
                "target": None,
                "detail": "未配置车端 Web 服务地址，无法读取实时状态",
                "status": None,
            }
        try:
            async with self._client(self.timeout) as client:
                response = await client.get(self._url("/api/status"))
                response.raise_for_status()
                return {
                    "ok": True,
                    "gateway": self.mode,
                    "target": self._url("/api/status"),
                    "detail": "ok",
                    "status": response.json(),
                }
        except Exception as exc:  # 车端不可达时降级
            return {
                "ok": False,
                "gateway": self.mode,
                "target": self._url("/api/status"),
                "detail": f"车端状态接口不可用：{exc}",
                "status": None,
            }

    async def send_command(
        self,
        robot_id: str,
        command: str,
        *,
        speed: float | None = None,
        params: dict[str, Any] | None = None,
        robot_code: str | None = None,
    ) -> dict[str, Any]:
        built = self.build_command(
            robot_id, command, speed=speed, params=params, robot_code=robot_code
        )
        if not self.base_url:
            return {
                "ok": False,
                "gateway": self.mode,
                "target": None,
                "detail": "未配置车端 Web 服务地址，命令已记录但未下发",
                "command": built,
                "response": None,
            }
        try:
            path, body = ("/api/speed", built["payload"]) if command == "speed_scale" else ("/api/command", built)
            async with self._client(self.timeout) as client:
                response = await client.post(self._url(path), json=body)
                response.raise_for_status()
                return {
                    "ok": True,
                    "gateway": self.mode,
                    "target": self._url(path),
                    "detail": "ok",
                    "command": built,
                    "response": _safe_json(response),
                }
        except Exception as exc:
            return {
                "ok": False,
                "gateway": self.mode,
                "target": self._url(path),
                "detail": f"命令下发失败：{exc}",
                "command": built,
                "response": None,
            }

    async def emergency_stop(
        self,
        robot_id: str,
        *,
        enabled: bool = True,
        reason: str = "",
        robot_code: str | None = None,
    ) -> dict[str, Any]:
        built = {
            "robot_id": robot_code or robot_id,
            "type": "emergency_stop",
            "topic": "/robot/emergency_stop/set",
            "payload": {"enabled": enabled, "reason": reason},
        }
        if not self.base_url:
            return {
                "ok": False,
                "gateway": self.mode,
                "target": None,
                "detail": "未配置车端 Web 服务地址，急停请求已记录但未下发",
                "command": built,
                "response": None,
            }
        try:
            async with self._client(self.timeout) as client:
                response = await client.post(self._url("/api/emergency-stop"), json=built)
                response.raise_for_status()
                return {
                    "ok": True,
                    "gateway": self.mode,
                    "target": self._url("/api/emergency-stop"),
                    "detail": "ok",
                    "command": built,
                    "response": _safe_json(response),
                }
        except Exception as exc:
            return {
                "ok": False,
                "gateway": self.mode,
                "target": self._url("/api/emergency-stop"),
                "detail": f"急停下发失败：{exc}",
                "command": built,
                "response": None,
            }


def _safe_json(response: httpx.Response) -> Any:
    try:
        return response.json()
    except Exception:
        return response.text


def get_robot_gateway(base_url: str | None = None) -> RobotGateway:
    """按配置构造 Gateway；base_url 为空时回退到环境配置。"""
    return RobotGateway(base_url if base_url is not None else settings.robot_web_url or settings.robot_gateway_url)
