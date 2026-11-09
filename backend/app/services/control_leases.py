"""Single-worker host lease renewer. Never reacquires after loss or restart."""
import asyncio
import time
from dataclasses import dataclass
from uuid import uuid4

from ..db.session import SessionLocal
from ..core.diagnostic_context import context as diagnostic_context
from .diagnostics import emit as diagnostic_emit
from ..gateway import get_robot_gateway
from ..models import User
from .control_access import require_bound_vehicle


@dataclass
class HeldLease:
    robot_id: str
    address: str
    user_id: str
    permissions: frozenset
    controller_id: str
    control_epoch: str
    owner: str
    sequence: int = 0
    run_id: str | None = None
    purpose: str = "navigation"
    drive_sequence: int = 0
    forward_limit_mps: float | None = None

    def identity(self):
        return {"controller_id": self.controller_id, "control_epoch": self.control_epoch, "owner": self.owner}

    def request(self, op):
        return {**self.identity(), "sequence": self.sequence, "op": op, "purpose": self.purpose,
                **({"forward_limit_mps": self.forward_limit_mps} if self.forward_limit_mps is not None else {})}


class ControlLeaseManager:
    def __init__(self):
        self.current = None
        self.generation = 0
        self.acquiring = False

    async def acquire(self, robot_id, address, user_id, permissions, expected, *, run_id=None, purpose="navigation", forward_limit_mps=None):
        if self.current or self.acquiring:
            raise RuntimeError("已有控制租约，请先停止或接管")
        lease = HeldLease(robot_id, address, user_id, frozenset(permissions),
                          expected["controller_id"], expected["control_epoch"], uuid4().hex, run_id=run_id, purpose=purpose,
                          forward_limit_mps=forward_limit_mps)
        self.acquiring = True
        generation = self.generation
        ids = diagnostic_context.get()
        token = diagnostic_context.set({**ids, 'robot_id': robot_id,
                                        'run_id': run_id if purpose == 'navigation' or forward_limit_mps else None})
        try:
            result = await get_robot_gateway(address).control_lease(lease.request("acquire"))
            if generation != self.generation or not self.matches(result, lease):
                await self.stop_remote(lease)
                raise RuntimeError("控制器未确认租约或停止已发生")
            self.current = lease
            diagnostic_emit('lease.changed', 'control_lease_acquired', module='control_leases',
                            details={'lease_purpose': purpose})
            return lease
        finally:
            diagnostic_context.reset(token)
            self.acquiring = False

    @staticmethod
    def matches(result, lease):
        ack = result.get("lease") or {}
        return (result.get("confirmed") is True and ack.get("fresh") is True
                and ack.get("blocked") is False and ack.get("controller_id") == lease.controller_id
                and ack.get("control_epoch") == lease.control_epoch and ack.get("owner") == lease.owner
                and ack.get("purpose", "navigation") == lease.purpose
                and (lease.forward_limit_mps is None or ack.get("forward_limit_mps") == lease.forward_limit_mps)
                and ack.get("sequence") == lease.sequence)

    async def stop_remote(self, lease):
        try:
            return await get_robot_gateway(lease.address).control_lease(lease.request("stop"))
        except Exception:
            return {"confirmed": False, "reason": "stop_response_unconfirmed"}

    async def stop(self):
        self.generation += 1
        lease, self.current = self.current, None
        return await self.stop_remote(lease) if lease else {"confirmed": False, "reason": "no_host_lease"}

    async def acquire_for_run(self, binding, user_id, permission, run_id, *, additional_permissions=(), purpose="navigation", forward_limit_mps=None):
        robot_id, address = binding
        if self.current or self.acquiring:
            raise RuntimeError("已有控制租约，请先停止或接管")
        generation = self.generation
        expected = await get_robot_gateway(address).control_lease()
        if (generation != self.generation or expected.get("fresh") is not True
                or expected.get("blocked") is not True
                or not expected.get("controller_id") or not expected.get("control_epoch")):
            raise RuntimeError("车辆控制权不可用，请核对停车状态")
        if forward_limit_mps is not None and expected.get("bounded_forward_supported") is not True:
            raise RuntimeError("车端尚未支持受限前进协议")
        return await self.acquire(robot_id, address, user_id, {permission, *additional_permissions}, expected,
                                  run_id=run_id, purpose=purpose, forward_limit_mps=forward_limit_mps)

    async def release_run(self, run_id, *, lease=None):
        current = self.current
        if current is None or current.run_id != run_id or (lease is not None and current is not lease):
            return
        self.current = None
        current.sequence += 1
        try:
            await get_robot_gateway(current.address).control_lease(current.request("release"))
        except Exception:
            # Renewal has stopped. The controller's deadline remains in force.
            pass

    async def observe_run(self, value):
        lease = self.current
        if (lease is not None and value.get("control_lease") == lease.identity()
                and value.get("state") in {"completed", "cancelled", "failed", "paused", "waiting_handover",
                                           "finished", "not_found", "fault"}):
            await self.release_run(value.get("run_id"), lease=lease)

    async def renew(self):
        lease = self.current
        if lease is None:
            return
        try:
            with SessionLocal() as db:
                user = db.get(User, lease.user_id)
                binding = require_bound_vehicle(db, lease.robot_id)
                if not user or not user.active or not (lease.permissions | {"robots.control"}) <= user.permissions or binding != (lease.robot_id, lease.address):
                    raise RuntimeError("控制权限或实车绑定已变化")
            lease.sequence += 1
            result = await get_robot_gateway(lease.address).control_lease(lease.request("renew"))
            if self.current is lease and not self.matches(result, lease):
                await self.stop()
        except Exception:
            if self.current is lease:
                await self.stop()

    async def run(self):
        try:
            while True:
                started = time.monotonic()
                await self.renew()
                await asyncio.sleep(max(0., 1. - (time.monotonic() - started)))
        finally:
            await self.stop()


control_lease_manager = ControlLeaseManager()
