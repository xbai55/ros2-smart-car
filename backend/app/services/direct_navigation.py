"""Lease-backed startup for the existing Nav2 preview workflow."""
import asyncio
import time
from contextlib import asynccontextmanager
from uuid import UUID

import httpx
from fastapi import HTTPException

from ..gateway import get_robot_gateway
from .capabilities import capability_snapshot
from .diagnostics import emit
from .control_leases import control_lease_manager
from .robot_context import robot_context_service, vehicle_binding


previews = {}


def register_preview(binding, user_id, plan_id, generation):
    now = time.monotonic()
    for key, (_, _, expires) in list(previews.items()):
        if expires <= now:
            previews.pop(key, None)
    if generation != control_lease_manager.generation:
        raise HTTPException(409, "预览期间控制权已变化，请重新规划")
    if len(previews) >= 256:
        previews.pop(next(iter(previews)))
    previews[(user_id, plan_id)] = (binding, generation, now + 60)


async def start_direct_navigation(db, binding, user, payload):
    if not {"robots.control", "maps.read"} <= user.permissions:
        raise HTTPException(403, "缺少机器人控制或地图读取权限")
    try:
        if not isinstance(payload, dict) or set(payload) != {"plan_id"}:
            raise ValueError()
        plan_id = str(UUID(payload["plan_id"]))
    except (ValueError, TypeError, AttributeError):
        raise HTTPException(422, "导航预览标识无效") from None
    context = robot_context_service.context(binding[0], binding)
    if not capability_snapshot(db, context)["capabilities"]["navigate"]["executable"]:
        raise HTTPException(409, "导航尚未就绪，请检查定位、传感器与地图状态")
    preview = previews.pop((user.id, plan_id), None)
    if (preview is None or preview[:2] != (binding, control_lease_manager.generation)
            or preview[2] <= time.monotonic()):
        raise HTTPException(409, "导航预览已过期或控制权已变化，请重新规划")
    lease = None
    try:
        lease = await control_lease_manager.acquire_for_run(binding, user.id, "maps.read", plan_id)
        if vehicle_binding(db) != binding or control_lease_manager.current is not lease:
            raise HTTPException(409, "车辆绑定或控制代际已变化")
        result = await get_robot_gateway(binding[1]).navigation_request(
            "start", {"plan_id": plan_id, "control_lease": lease.identity()})
        if not isinstance(result, dict) or result.get("ok") is not True or result.get("goal_id") != plan_id:
            raise HTTPException(502, "车端导航回执未确认")
        return result
    except (httpx.HTTPError, RuntimeError, ValueError, HTTPException, asyncio.CancelledError) as exc:
        emit("gateway.failed", "navigation_start_failed", module="direct_navigation", level="ERROR", exception=exc,
             details={"operation": "dispatch" if lease is not None else "acquire", "plan_id": plan_id,
                      "failures": [str(exc.detail) if isinstance(exc, HTTPException) else str(exc)[:450]]})
        if lease is not None:
            await control_lease_manager.release_run(plan_id, lease=lease)
        if isinstance(exc, (HTTPException, asyncio.CancelledError)):
            raise
        if isinstance(exc, httpx.HTTPStatusError) and exc.response.status_code < 500:
            try: detail=exc.response.json().get('detail','车端未接受导航')
            except ValueError:detail='车端未接受导航'
            message=detail.get('message',detail) if isinstance(detail,dict) else detail
            raise HTTPException(409, str(message)[:450]) from exc
        if isinstance(exc, httpx.TimeoutException):
            message = "导航通信超时，目标状态未确认，请停车后重新预览"
        elif isinstance(exc, httpx.HTTPStatusError):
            message = "Nav2 目标确认超时，请停车后重新预览" if exc.response.status_code == 504 else "车端导航服务异常"
        elif isinstance(exc, httpx.HTTPError):
            message = "导航通信异常，请检查连接"
        else:
            message = str(exc)[:450]
        emit("gateway.failed", "navigation_start_failed", module="direct_navigation", level="ERROR", exception=exc,
             details={"operation": "start", "plan_id": plan_id, "failures": [message]})
        raise HTTPException(409, message) from exc


@asynccontextmanager
async def navigation_parking(manager, stop, binding_is_current):
    """Share the parking proof and host-generation fence across navigation entries."""
    if manager.preparing_navigation or manager.acquiring:
        raise HTTPException(409, "导航交接进行中，请等待后重新预览")
    manager.preparing_navigation = True
    try:
        expected_generation = manager.generation + 1
        result = await stop()
        if (result.get("controller_confirmed") is not True
                or result.get("stationary_confirmed") is not True or result.get("errors")):
            raise HTTPException(409, "停车未确认，不能继续导航")
        generation = manager.generation
        if generation != expected_generation or not binding_is_current():
            raise HTTPException(409, "停车期间控制权已变化，请重试")
        yield generation, result
    finally:
        manager.preparing_navigation = False


async def prepare_navigation_preview(db, binding, user, payload, stop):
    """Fence old work and confirm stop before binding the vehicle preview epoch."""
    try:
        async with navigation_parking(control_lease_manager, stop, lambda: vehicle_binding(db) == binding) as (generation, _):
            preview = await get_robot_gateway(binding[1]).navigation_request("plan", payload)
            if not isinstance(preview, dict) or not isinstance(preview.get("plan_id"), str):
                raise HTTPException(502, "车端未返回有效的预览")
            if vehicle_binding(db) != binding:
                raise HTTPException(409, "车辆绑定已变化，请重新预览")
            register_preview(binding, user.id, preview["plan_id"], generation)
            return preview
    except HTTPException as exc:
        emit("gateway.failed", "navigation_preparation_rejected", module="direct_navigation", level="ERROR",
             details={"operation": "prepare", "failures": [str(exc.detail)]})
        raise
    except httpx.HTTPStatusError as exc:
        try: detail = exc.response.json().get("detail", "车端拒绝路线预览")
        except ValueError: detail = "车端拒绝路线预览"
        raise HTTPException(exc.response.status_code, detail) from exc
    except httpx.HTTPError as exc:
        emit("gateway.failed", "navigation_communication_failed", module="direct_navigation", level="ERROR", exception=exc)
        raise HTTPException(502, "导航预览通信异常，请检查连接") from exc
