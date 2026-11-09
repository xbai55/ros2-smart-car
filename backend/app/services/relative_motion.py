"""Deterministic bounded forward task using existing authorized drive commands.

No LLM velocities, arbitrary coordinates, map guesses, or automatic retry.
"""
import asyncio
import math
import time

from fastapi import HTTPException

from ..gateway import get_robot_gateway
from .control_leases import control_lease_manager
from .operator_control import send_drive

MAX_SPEED = .10
MAX_DURATION = 4.5


def pose(status):
    value = status.get("relative_motion") or {}
    keys = ("x","y","yaw","age_sec","stamp","cruise_speed_mps")
    if (value.get("ok") is not True or value.get("frame_id") != "odom"
            or any(type(value.get(k)) not in (int,float) or not math.isfinite(value[k]) for k in keys)
            or not 0 <= value["age_sec"] < .5 or not .01 <= value["cruise_speed_mps"] <= 1):
        raise HTTPException(409, "短距任务缺少新鲜、有效的实际里程计或速度标定")
    return value


from .diagnostics import emit as diagnostic_emit


async def execute_relative(binding, user, step, run_id, guard):
    distance = step["distance_m"]
    if type(distance) not in (int,float) or not math.isfinite(distance) or not .05 <= distance <= .20:
        raise HTTPException(422, "前进距离必须为5至20厘米")
    gateway, manager = get_robot_gateway(binding[1]), control_lease_manager
    lease, old_scale, stop_result = None, None, None
    achieved = False
    travelled = 0.
    stop_reason = 'relative_interrupted'
    try:
        guard()
        status = await gateway.get_status(binding[0])
        if not status.get("ok"):
            raise HTTPException(409, "车端状态不可用")
        initial = status["status"]
        origin = pose(initial)
        if initial.get("mode") != "stop" or initial.get("emergency_stop") is not False:
            raise HTTPException(409, "请先停车并核对急停")
        stopped = await gateway.stop()
        if stopped.get("stationary_confirmed") is not True:
            raise HTTPException(409, "尚未确认车辆静止")
        guard()
        lease = await manager.acquire_for_run(binding, user.id, "robots.control", run_id,
            additional_permissions={"assistant.use"}, purpose="manual", forward_limit_mps=MAX_SPEED)
        old_scale = initial.get("speed_scale", 1.)
        scale = min(1., MAX_SPEED/origin["cruise_speed_mps"])
        async with gateway._client(2) as client:
            response = await client.post(gateway.base_url+"/api/speed", json={"scale":scale})
            response.raise_for_status()
        guard()
        changed = await gateway.operator_request("mode", {"mode":"manual","control_lease":lease.identity()})
        if changed.get("ok") is not True:
            raise HTTPException(409, "车端未确认短距驾驶模式")
        # Reference position comes from fresh odometry after acquiring control.
        measured = await gateway.get_status(binding[0])
        origin = pose(measured.get("status") or {})
        last_stamp = origin["stamp"]
        async with gateway._client(1) as channel:
            started = time.monotonic()
            while time.monotonic()-started < MAX_DURATION:
                guard()
                if manager.current is not lease:
                    raise HTTPException(409, "短距执行已被停止或接管")
                response = await channel.get(gateway.base_url+"/api/status")
                response.raise_for_status()
                status = response.json()
                if (status.get("mode") != "manual"
                        or status.get("emergency_stop") is not False
                        or any((status.get(k) or {}).get("ok") is not True for k in ("lidar","odom","tf"))):
                    raise HTTPException(409, "短距任务传感器、模式或急停状态已变化")
                current = pose(status)
                if current["stamp"] < last_stamp:
                    raise HTTPException(409, "里程计时间发生回退")
                last_stamp = current["stamp"]
                dx,dy = current["x"]-origin["x"], current["y"]-origin["y"]
                travelled = dx*math.cos(origin["yaw"])+dy*math.sin(origin["yaw"])
                lateral = -dx*math.sin(origin["yaw"])+dy*math.cos(origin["yaw"])
                yaw_delta = math.atan2(math.sin(current["yaw"]-origin["yaw"]),math.cos(current["yaw"]-origin["yaw"]))
                if travelled < -.02 or abs(lateral) > .04 or abs(yaw_delta) > .15 or math.hypot(dx,dy) > .30:
                    raise HTTPException(409, "实际运动偏离受限前进范围，已停止")
                if travelled >= distance:
                    achieved = True
                    break
                guard()
                if time.monotonic()-started >= MAX_DURATION:
                    break
                await send_drive(binding,user,"forward",run_id,lease.drive_sequence+1, client=channel)
                await asyncio.sleep(.1)
        stop_reason = 'relative_distance_reached' if achieved else 'relative_time_limit'
    finally:
        # A cancelled coroutine also follows the existing stop path.
        if lease is not None and manager.current is lease:
            diagnostic_emit('task.changed', stop_reason, module='relative_motion', robot_id=binding[0],
                            run_id=run_id, level='INFO' if achieved else 'WARN',
                            details={'state': 'stopping', 'requested': distance, 'distance_m': travelled})
            try:
                stop_result = await gateway.stop()
            finally:
                await manager.release_run(run_id,lease=lease)
            if stop_result.get("stationary_confirmed") is True and old_scale is not None:
                async with gateway._client(2) as client:
                    response = await client.post(gateway.base_url+"/api/speed",json={"scale":old_scale})
                    response.raise_for_status()
    if not stop_result or stop_result.get("stationary_confirmed") is not True:
        raise HTTPException(409, "短距任务尚未确认停车")
    return {"run_id":run_id,"state":"completed" if achieved else "failed",
            "message":f"里程计前进约{travelled*100:.1f}厘米，已确认停车" +
                       ("" if achieved else "；到达时限，未达到目标距离")}
