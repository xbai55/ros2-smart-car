"""Scoped manual and mapping control shared by both host APIs."""
import asyncio
import math
from uuid import uuid4

import httpx
from fastapi import HTTPException

from ..gateway import get_robot_gateway
from .control_access import require_bound_vehicle
from .control_leases import control_lease_manager


DRIVE_COMMANDS = frozenset(("forward", "backward", "left", "right", "turn_l", "turn_r", "rotate_left", "rotate_right", "stop"))


async def select_operator_mode(db, binding, user, path, mode, stop, *, client_id=None):
    manager = control_lease_manager
    permissions = {"robots.control"} | ({"maps.manage"} if mode == "mapping" else set())
    if not permissions <= user.permissions:
        raise HTTPException(403, "缺少机器人控制或建图权限")
    if mode not in {"manual", "mapping", "auto", "color_track", "object_follow"}:
        raise HTTPException(409, "该模式尚未接入受控运动入口")
    if not binding[1]:
        raise HTTPException(503, "未配置车端地址")
    if client_id is not None and (not isinstance(client_id, str) or not 1 <= len(client_id) <= 128):
        raise HTTPException(422, '驾驶客户端标识无效')
    current = manager.current
    if (path == 'mode' and mode == 'manual' and client_id and current is not None
            and current.client_id == client_id and current.user_id == user.id
            and (current.robot_id, current.address) == binding and current.purpose == mode
            and current.permissions <= user.permissions):
        gateway = get_robot_gateway(binding[1])
        try:
            live = await gateway.control_lease()
            status = await gateway.get_status(binding[0])
            vehicle = status.get('status') or {}
            if (manager.current is current and live.get('fresh') is True and live.get('blocked') is False
                    and live.get('purpose') == mode and all(live.get(k) == v for k,v in current.identity().items())
                    and vehicle.get('mode') == mode and vehicle.get('emergency_stop') is False
                    and require_bound_vehicle(db, binding[0]) == binding):
                return {'ok': True, 'mode': mode, 'drive_id': current.run_id, 'reused': True,
                        'motion_epoch': live.get('motion_epoch'), 'command_valid_until': live.get('command_valid_until'),
                        'drive_seq_floor': max(current.drive_sequence, live.get('drive_sequence', -1)),
                        'intent_seq_floor': max(0, live.get('intent_sequence', 0)), 'takeover_warnings': []}
        except (httpx.HTTPError, RuntimeError, ValueError):
            pass
    generation = manager.generation + 1
    stopped = await stop()
    if (stopped.get("controller_confirmed") is not True or stopped.get("stationary_confirmed") is not True
            or generation != manager.generation
            or require_bound_vehicle(db, binding[0]) != binding):
        raise HTTPException(409, "未确认车辆静止或控制权已变化，请核对后重试")
    run_id, lease = uuid4().hex, None
    try:
        lease = await manager.acquire_for_run(binding, user.id, "robots.control", run_id,
                                              additional_permissions=permissions, purpose=mode)
        if manager.current is not lease or require_bound_vehicle(db, binding[0]) != binding:
            raise HTTPException(409, "车辆绑定或控制权已变化")
        lease.client_id = client_id
        wire = {"control_lease": lease.identity()}
        if path == "mode":
            wire["mode"] = mode
        result = await get_robot_gateway(binding[1]).operator_request(path, wire)
        if (not isinstance(result, dict) or result.get("ok") is not True
                or (path == "mode" and result.get("mode") != mode) or manager.current is not lease
                or require_bound_vehicle(db, binding[0]) != binding):
            raise HTTPException(409, "车端模式或控制权未确认")
        return {**result, "drive_id": run_id, "motion_epoch": lease.motion_epoch, "command_valid_until": lease.command_valid_until, "takeover_warnings": stopped.get("errors", [])}
    except (httpx.HTTPError, RuntimeError, ValueError, HTTPException, asyncio.CancelledError) as exc:
        if lease is not None:
            await manager.release_run(run_id, lease=lease)
        if isinstance(exc, (HTTPException, asyncio.CancelledError)):
            raise
        raise HTTPException(409, "车端未确认驾驶模式，请核对车辆状态") from exc


async def send_drive(binding, user, command, drive_id, sequence, *, client=None, intent_seq=None, motion_epoch=None, command_deadline=None):
    if (not isinstance(drive_id, str) or not 1 <= len(drive_id) <= 128
            or command not in DRIVE_COMMANDS or type(sequence) is not int or not 1 <= sequence <= 2**53 - 1):
        raise HTTPException(422, "手动指令或序号无效")
    lease = control_lease_manager.current
    if (lease is None or lease.purpose not in ("manual", "mapping") or lease.run_id != drive_id
            or (lease.robot_id, lease.address, lease.user_id) != (*binding, user.id)
            or not lease.permissions <= user.permissions):
        raise HTTPException(409, "驾驶控制权已失效，请重新选择驾驶模式")
    if intent_seq is None and lease.forward_limit_mps is not None:
        intent_seq, motion_epoch = 1, lease.motion_epoch
        live = await get_robot_gateway(binding[1]).control_lease()
        if (live.get('fresh') is not True or live.get('blocked') is not False
                or live.get('motion_epoch') != lease.motion_epoch
                or any(live.get(k) != v for k, v in lease.identity().items())):
            raise HTTPException(409, '短距运动的控制代次已变化，已停止')
        command_deadline = live.get('command_valid_until')
    extended = intent_seq is not None or motion_epoch is not None or command_deadline is not None
    if extended:
        if type(intent_seq) is not int or not 1 <= intent_seq <= 2**53 - 1 or (command != 'stop' and not isinstance(motion_epoch, str)):
            raise HTTPException(409, "请松开后重新按下驾驶按钮，或更新控制客户端")
        if command != 'stop' and (type(command_deadline) not in (int, float) or not math.isfinite(command_deadline)):
            raise HTTPException(409, '驾驶指令缺少车端有效期，请更新客户端')
    if sequence <= lease.drive_sequence:
        raise HTTPException(409, "已收到更新的驾驶指令")
    lease.drive_sequence = sequence
    try:
        wire = {"command": command, "drive_seq": sequence, "control_lease": lease.identity()}
        if extended:
            wire.update(intent_seq=intent_seq, motion_epoch=motion_epoch, command_deadline=command_deadline)
        gateway = get_robot_gateway(binding[1])
        if client is None:
            result = await gateway.operator_request("command", wire)
        else:
            response = await client.post(gateway.base_url + "/api/command", json=wire)
            response.raise_for_status()
            result = response.json()
    except (httpx.HTTPError, RuntimeError, ValueError) as exc:
        raise HTTPException(409, "车端未确认手动指令") from exc
    if not isinstance(result, dict) or result.get("ok") is not True:
        raise HTTPException(409, "车端未确认手动指令")
    return result
