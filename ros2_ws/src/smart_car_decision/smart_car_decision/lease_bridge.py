"""HTTP-to-controller lease handshake; publication is not acknowledgement."""
import asyncio
import math
import time
from uuid import uuid4
from .diagnostic_log import request_ids


class LeaseBridge:
    def __init__(self, node, clock=time.monotonic, sleep=asyncio.sleep):
        self.node, self.clock, self.sleep = node, clock, sleep

    def snapshot(self):
        value = dict(getattr(self.node, "control_lease_ack", {}))
        received = value.pop("received_at", None)
        age = self.clock() - received if type(received) in (int, float) else float("inf")
        fresh = math.isfinite(age) and 0 <= age <= .5
        value["fresh"] = fresh
        if not fresh:
            value["blocked"] = True
            value["reason"] = "controller_ack_stale"
        return value

    def accepts(self, identity, *, purpose="navigation"):
        live = self.snapshot()
        return (isinstance(identity, dict) and live["fresh"] and live.get("blocked") is False
                and live.get("purpose", "navigation") == purpose
                and all(isinstance(identity.get(key), str) and identity[key] == live.get(key)
                        for key in ("controller_id", "control_epoch", "owner")))

    async def request(self, payload):
        if not isinstance(payload, dict) or payload.get("op") not in {"acquire", "renew", "release", "stop"}:
            raise ValueError("控制租约操作无效")
        before = self.snapshot()
        if not before.get("fresh"):
            raise RuntimeError("控制器回执陈旧，无法确认控制权")
        if payload.get("controller_id") != before.get("controller_id"):
            raise RuntimeError("控制器已重启")
        if payload["op"] != "stop":
            if payload.get("control_epoch") != before.get("control_epoch"):
                raise RuntimeError("控制代际已失效")
            if not isinstance(payload.get("owner"), str) or not 1 <= len(payload["owner"]) <= 128 or type(payload.get("sequence")) is not int:
                raise ValueError("租约身份或序号无效")
        ident = uuid4().hex
        wire = {key: payload[key] for key in ("op", "controller_id", "control_epoch", "owner", "sequence", "purpose", "forward_limit_mps")
                if key in payload}
        wire["request_id"] = ident
        ids = request_ids.get()
        if ids:
            wire['diagnostic'] = ids
        self.node.publish_control_lease(wire)
        deadline = self.clock() + .8
        while self.clock() < deadline:
            value = self.snapshot()
            if value.get("fresh") and value.get("last_request_id") == ident:
                return {"confirmed": True, "lease": value}
            await self.sleep(.02)
        return {"confirmed": False, "reason": "controller_response_unconfirmed", "lease": self.snapshot()}
