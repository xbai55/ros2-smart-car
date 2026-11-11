"""Shared authenticated dispatch for visual search."""
import asyncio
import hashlib
import json

import httpx
from fastapi import HTTPException

from ..gateway import get_robot_gateway
from .capabilities import capability_snapshot
from .control_leases import control_lease_manager
from .robot_context import robot_context_service, vehicle_binding


class SearchRequestRejected(HTTPException):
    """An explicit validation rejection, not a lost dispatch acknowledgement."""
    def __init__(self):
        super().__init__(422, '搜索请求被车端拒绝，请检查目标名称或英文提示词')


async def execute_search(db, binding, user, operation, payload, *, guard=None, trial_context=None):
    if not {"robots.control", "patrol.manage"} <= user.permissions:
        raise HTTPException(403, "缺少机器人控制或巡检管理权限")
    if not isinstance(payload, dict) or "control_lease" in payload:
        raise HTTPException(422, "搜索请求格式无效，控制租约由主机签发")
    run_id = payload.get("run_id")
    if not isinstance(run_id, str) or not 1 <= len(run_id) <= 128:
        raise HTTPException(422, "搜索请求标识无效")
    action = payload.get("action") if operation == "action" else None
    if operation == "action" and (not isinstance(action, str) or action not in {"pause", "cancel", "finish", "resume", "continue"}):
        raise HTTPException(422, "搜索操作无效")
    gateway = get_robot_gateway(binding[1])
    lease = None
    dispatching = False
    fingerprint = None
    try:
        if operation == "start":
            travel = payload.get("travel")
            if not isinstance(travel, str) or travel not in {"stationary", "patrol"}:
                raise HTTPException(422, "请选择静止观察或地图巡逻")
            fingerprint = hashlib.sha256(json.dumps(payload, sort_keys=True, allow_nan=False).encode()).hexdigest()
            previous = await gateway.search_request(run_id)
            if previous:
                if previous.get("request_fingerprint") != fingerprint and not (
                        previous.get("request_fingerprint") is None and previous.get("state") == "cancelled"):
                    raise HTTPException(409, "同一搜索标识的请求已变化")
                return previous
        elif action in {"resume", "continue"}:
            previous = await gateway.search_request(run_id)
            if not previous or previous.get("state") not in {"paused", "found"}:
                raise HTTPException(409, "当前搜索阶段不能恢复")
            travel = previous.get("travel")
        else:
            travel = None

        wire = dict(payload)
        if guard:
            guard()
        if travel:
            if travel not in {"patrol", "stationary"}:
                raise HTTPException(409, "当前搜索方式不可恢复")
            if travel == "patrol" and "maps.read" not in user.permissions:
                raise HTTPException(403, "缺少地图读取权限")
            context = robot_context_service.context(binding[0], binding)
            capability = "patrol_search" if travel == "patrol" else "observe_target"
            current = capability_snapshot(db, context)["capabilities"][capability]
            if not current["executable"]:
                if travel != "stationary" or trial_context is None or not current["supported"] or not current["ready"]:
                    raise HTTPException(409, "搜索尚未就绪或缺少当前版本的实车验收")
                from .assistant_trials import require_trial
                require_trial(db, user, trial_context[0], capability, current["fingerprint"], trial_context[1])
            if travel == "patrol":
                lease = await control_lease_manager.acquire_for_run(
                    binding, user.id, "patrol.manage", run_id, additional_permissions={"maps.read"})
                wire["control_lease"] = lease.identity()

        if vehicle_binding(db) != binding or (lease and control_lease_manager.current is not lease):
            raise HTTPException(409, "控制租约或实车绑定已变化")
        if guard:
            guard()
        dispatching = True
        result = await gateway.search_request(run_id, operation=operation, payload=wire)
    except (httpx.HTTPError, ValueError, RuntimeError) as exc:
        result = None
        if isinstance(exc, httpx.HTTPStatusError) and exc.response.status_code in {400, 422}:
            if lease:
                await control_lease_manager.release_run(run_id, lease=lease)
            raise SearchRequestRejected() from exc
        if dispatching and (operation == "start" or action in {"resume", "continue"}):
            try:
                found = await gateway.search_request(run_id)
                if found:
                    matches = (found.get("request_fingerprint") == fingerprint if operation == "start"
                               else lease is not None)
                    if matches and (lease is None or found.get("control_lease") == lease.identity()):
                        result = found
            except (httpx.HTTPError, ValueError, RuntimeError):
                pass
        if result is None:
            if lease:
                await control_lease_manager.release_run(run_id, lease=lease)
            if isinstance(exc, httpx.HTTPStatusError) and exc.response.status_code < 500:
                raise HTTPException(409, "车端拒绝搜索操作，请核对运行状态") from exc
            raise HTTPException(502, "搜索状态未确认，请按运行 ID 查询") from exc
    except (HTTPException, asyncio.CancelledError):
        if lease:
            await control_lease_manager.release_run(run_id, lease=lease)
        raise
    if lease is not None and result.get("control_lease") != lease.identity():
        await control_lease_manager.release_run(run_id, lease=lease)
    if result["state"] in {"cancelled", "finished", "not_found", "fault"}:
        await control_lease_manager.observe_run(result)
    return result
