"""Lease-backed startup for the existing Nav2 preview workflow."""
import asyncio
import time
from uuid import UUID

import httpx
from fastapi import HTTPException

from ..gateway import get_robot_gateway
from .capabilities import capability_snapshot
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
        if lease is not None:
            await control_lease_manager.release_run(plan_id, lease=lease)
        if isinstance(exc, (HTTPException, asyncio.CancelledError)):
            raise
        if isinstance(exc, httpx.HTTPStatusError) and exc.response.status_code < 500:
            try: detail=exc.response.json().get('detail','车端未接受导航')
            except ValueError:detail='车端未接受导航'
            message=detail.get('message',detail) if isinstance(detail,dict) else detail
            raise HTTPException(409, str(message)[:450]) from exc
        raise HTTPException(409, "导航启动未确认，请核对车辆状态") from exc
