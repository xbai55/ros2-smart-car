"""Authenticated compatibility entry for existing vehicle control pages."""
import re
import asyncio

import httpx
from fastapi import APIRouter, Depends, HTTPException, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import Response
from sqlalchemy.orm import Session

from ..deps import get_db, require_permission, get_current_user
from ...db.session import SessionLocal
from ...gateway import get_robot_gateway
from ...models import User
from ...services.ops import record_audit
from ...services.control_access import require_bound_vehicle
from ...services.capabilities import capability_snapshot
from ...services.robot_context import robot_context_service
from ...services.search_execution import execute_search
from ...services.windows_credentials import machine_token
from ...services.direct_navigation import register_preview, start_direct_navigation
from ...services.operator_control import DRIVE_COMMANDS, select_operator_mode, send_drive
from ...services.control_leases import control_lease_manager
from .robots import revoke_host_execution, robot_stop

router = APIRouter()
READ_PATHS = {"status", "map", "video", "avoidance", "search", "search/capabilities", "vision/status", "vision/settings",
              "navigation/runtime", "navigation/task", "navigation/config", "navigation/status", "navigation/capabilities"}


def socket_access(token):
    with SessionLocal() as db:
        user = get_current_user(authorization="Bearer " + token, db=db)
        if "robots.read" not in user.permissions:
            raise HTTPException(403, "缺少机器人读取权限")
        return require_bound_vehicle(db)


@router.websocket("/ws/status")
async def vehicle_status_socket(socket: WebSocket):
    from websockets.legacy.client import connect
    await socket.accept()
    try:
        message = await asyncio.wait_for(socket.receive_json(), timeout=5)
        if not isinstance(message, dict) or message.get("type") != "authenticate" or not isinstance(message.get("token"), str):
            await socket.close(code=4401)
            return
        token = message["token"]
        binding = socket_access(token)
        gateway = get_robot_gateway(binding[1])
        if not gateway.base_url:
            await socket.close(code=1013)
            return
        url = gateway.base_url.replace("https://", "wss://", 1).replace("http://", "ws://", 1) + "/ws/status"
        headers = {"X-InsightRover-Service-Token": machine_token()}
        async with connect(url, extra_headers=headers, open_timeout=4, max_size=8*1024*1024) as upstream:
            async def watch_disconnect():
                while (await socket.receive())["type"] != "websocket.disconnect":
                    pass
            disconnected = asyncio.create_task(watch_disconnect())
            try:
                while not disconnected.done():
                    if socket_access(token) != binding:
                        await socket.close(code=4403)
                        return
                    try:
                        frame = await asyncio.wait_for(upstream.recv(), timeout=1)
                    except asyncio.TimeoutError:
                        continue
                    if isinstance(frame, bytes):
                        await socket.send_bytes(frame)
                    else:
                        await socket.send_text(frame)
            finally:
                disconnected.cancel()
                await asyncio.gather(disconnected, return_exceptions=True)
    except HTTPException:
        await socket.close(code=4403)
    except WebSocketDisconnect:
        return
    except Exception:
        try:
            await socket.close(code=1013)
        except RuntimeError:
            pass


@router.get("/api/control/{path:path}")
async def vehicle_read(path: str, request: Request, db: Session = Depends(get_db),
                       user: User = Depends(require_permission("robots.read"))):
    if path not in READ_PATHS:
        raise HTTPException(404, "接口不存在")
    required = "maps.read" if path == "map" or path.startswith("navigation/") else None
    if path.startswith("vision/") or path in {"search", "search/capabilities"}:
        required = "patrol.read"
    if required and required not in user.permissions:
        raise HTTPException(403, "缺少相应业务读取权限")
    robot_id, address = require_bound_vehicle(db)
    if path in {"search/capabilities", "navigation/capabilities"}:
        context = robot_context_service.context(robot_id, (robot_id, address))
        capabilities = capability_snapshot(db, context)["capabilities"]
        keys = ("observe_target", "patrol_search") if path == "search/capabilities" else ("navigate",)
        return {key: capabilities[key] for key in keys}
    gateway = get_robot_gateway(address)
    if not gateway.base_url:
        raise HTTPException(503, "未配置车端地址")
    # Video is a finite JPEG request, never an unbounded MJPEG body.
    params = {"frame": "true"} if path == "video" else {}
    if path == "search" and "run_id" in request.query_params:
        run_id = request.query_params["run_id"]
        if not 1 <= len(run_id) <= 128:
            raise HTTPException(422, "搜索请求标识无效")
        params["run_id"] = run_id
    try:
        async with gateway._client(5) as client:
            response = await client.get(gateway.base_url + "/api/" + path, params=params)
    except httpx.HTTPError:
        raise HTTPException(502, "读取车端数据失败") from None
    return Response(response.content, status_code=response.status_code,
                    media_type=response.headers.get("content-type", "application/json"),
                    headers={"Cache-Control": "no-store"})


PATHS = re.compile(r"^(mode|command|emergency-stop|speed|avoidance|color-target|mode-obstacle-stop-distance|mapping/[\w/-]+|navigation/[\w/-]+|search/(start|action)|vision/settings)$")


def authorize_vehicle_write(path, payload, permissions):
    if "robots.control" not in permissions:
        raise HTTPException(403, "缺少机器人控制权限")
    if path.startswith('navigation/handoff-') or path == 'mapping/finish-for-tasks':
        raise HTTPException(409, '请通过地图准备接口操作')
    if path in {"navigation/task", "navigation/task/action"}:
        # Business task creation and actions must retain their persistent records.
        raise HTTPException(409, "请通过业务任务接口操作")
    if path == "command":
        if (not isinstance(payload, dict) or not isinstance(payload.get("command"), str)
                or payload["command"] not in DRIVE_COMMANDS
                or (set(payload) not in ({"command", "drive_id", "drive_seq"}, {"command", "drive_id", "drive_seq", "intent_seq", "motion_epoch", "command_deadline"})
                    and payload != {"command": "stop"})):
            raise HTTPException(422, "手动指令格式无效")
    if path == "mode" and (not isinstance(payload, dict) or set(payload) not in ({"mode"}, {"mode", "client_id"})
                           or not isinstance(payload["mode"], str)):
        raise HTTPException(422, "驾驶模式无效")
    required = set()
    if path == "mode" and isinstance(payload, dict) and payload.get("mode") == "mapping":
        required.add("maps.manage")
    if path.startswith("mapping/") or path in {
        "navigation/load-map", "navigation/initial-pose", "navigation/calibration",
        "navigation/places",
    } or path.startswith("navigation/places/"):
        required.add("maps.manage")
    if path.startswith("search/"):
        required.add("patrol.manage")
    if path in {"navigation/plan", "navigation/start"}:
        required.add("maps.read")
    if required - permissions:
        raise HTTPException(403, "缺少相应业务操作权限")


@router.api_route("/api/{path:path}", methods=["POST", "PUT", "PATCH", "DELETE"], include_in_schema=False)
@router.api_route("/api/control/{path:path}", methods=["POST", "PUT", "PATCH", "DELETE"], include_in_schema=False)
async def vehicle_write(path: str, request: Request, db: Session = Depends(get_db),
                        user: User = Depends(require_permission("robots.control"))):
    if not PATHS.fullmatch(path) or ".." in path:
        raise HTTPException(404, "接口不存在")
    raw = await request.body()
    if len(raw) > 1024 * 1024:
        raise HTTPException(413, "请求过大")
    try:
        payload = await request.json() if raw else {}
    except ValueError:
        raise HTTPException(422, "请求格式无效") from None
    authorize_vehicle_write(path, payload, user.permissions)
    robot_id, address = require_bound_vehicle(db)
    if path in {"command", "mode", "mapping/restart"}:
        if request.method != "POST":
            raise HTTPException(405, "驾驶操作须使用 POST")

        async def stop_bound():
            return await robot_stop(robot_id, db, user)

        if payload in ({"command": "stop"}, {"mode": "stop"}):
            result = await stop_bound()
            return {**payload, "ok": result["controller_confirmed"], **result}
        binding = (robot_id, address)
        if path == "command":
            return await send_drive(binding, user, payload["command"], payload["drive_id"], payload["drive_seq"],
                                    intent_seq=payload.get("intent_seq"), motion_epoch=payload.get("motion_epoch"),
                                    command_deadline=payload.get("command_deadline"))
        result = await select_operator_mode(db, binding, user, path, "mapping" if path == "mapping/restart" else payload["mode"],
                                            stop_bound, client_id=payload.get("client_id"))
        record_audit(db, user, "vehicle." + path.replace("/", "."), "robot", robot_id,
                     after={"mode": result.get("mode", "mapping")})
        db.commit()
        return result
    if path == "emergency-stop":
        if not isinstance(payload, dict) or type(payload.get("enabled")) is not bool:
            raise HTTPException(422, "急停状态必须明确指定")
        if payload["enabled"]:
            revoke_host_execution(db, robot_id)
    if path in {"navigation/start", "navigation/cancel"}:
        if request.method != "POST":
            raise HTTPException(405, "导航操作须使用 POST")
        if path == "navigation/cancel":
            stopped = await robot_stop(robot_id, db, user)
            return {"ok": stopped["controller_confirmed"], **stopped}
        result = await start_direct_navigation(db, (robot_id, address), user, payload)
        record_audit(db, user, "vehicle.navigation.start", "robot", robot_id, after={"goal_id": result["goal_id"]})
        db.commit()
        return result
    if path in {"search/start", "search/action"}:
        if request.method != "POST":
            raise HTTPException(405, "搜索操作须使用 POST")
        result = await execute_search(db, (robot_id, address), user, path.split("/")[1], payload)
        record_audit(db, user, "vehicle." + path.replace("/", "."), "robot", robot_id,
                     after={"run_id": result["run_id"], "state": result["state"]})
        db.commit()
        return result
    gateway = get_robot_gateway(address)
    if not gateway.base_url:
        raise HTTPException(503, "未配置车端地址")
    headers = {"content-type": "application/json"}
    token = machine_token()
    if token:
        headers["X-InsightRover-Service-Token"] = token
    generation = control_lease_manager.generation
    try:
        async with httpx.AsyncClient(trust_env=False, timeout=httpx.Timeout(60, connect=4)) as client:
            result = await client.request(request.method, gateway.base_url + "/api/" + path,
                                          content=raw, headers=headers)
    except httpx.HTTPError:
        raise HTTPException(502, "车端响应未确认，请核对执行状态") from None
    if path == "navigation/plan" and result.is_success:
        try:
            preview = result.json()
            if not isinstance(preview.get("plan_id"), str):
                raise ValueError()
        except (ValueError, AttributeError):
            raise HTTPException(502, "车端未返回有效的预览") from None
        register_preview((robot_id, address), user.id, preview["plan_id"], generation)
    record_audit(db, user, "vehicle." + path.replace("/", "."), "robot", robot_id,
                 after={"http_status": result.status_code})
    db.commit()
    return Response(result.content, status_code=result.status_code,
                    media_type=result.headers.get("content-type", "application/json"))
