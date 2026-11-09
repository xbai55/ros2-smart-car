"""Read-only polling for the single configured physical vehicle."""
import asyncio
from datetime import datetime, timezone
import logging
import time

from sqlalchemy import select

from ..core.config import settings
from ..db.session import SessionLocal
from ..gateway import get_robot_gateway
from ..models import AppSetting, Robot
from .realtime import get_realtime_store
from .diagnostics import emit as diagnostic_emit

MAX_AGE = 2.5
FIELDS = ("mode", "status", "network", "position", "map_pose", "speed", "battery",
          "emergency_stop", "lidar", "odom", "tf", "navigation", "avoidance",
          "vision", "search", "search_control", "navigation_task", "ros2_status_age_sec",
          "component_manifest", "active_map_key", "relative_motion")
logger = logging.getLogger(__name__)


def vehicle_binding(db):
    values = dict(db.execute(select(AppSetting.key, AppSetting.value).where(
        AppSetting.key.in_(("physical_robot_id", "robot_web_url", "robot_gateway_url"))
    )).all())
    return (values.get("physical_robot_id", "r-001"),
            values.get("robot_web_url") or values.get("robot_gateway_url")
            or settings.robot_web_url or settings.robot_gateway_url)


class RobotContextService:
    def __init__(self):
        self.sample = None
        self.reason = "telemetry_pending"

    def context(self, robot_id, binding):
        if robot_id != binding[0]:
            return {"robot_id": robot_id, "available": False, "reason": "robot_not_bound", "telemetry": None}
        sample = self.sample
        if sample is None or sample[0] != binding:
            return {"robot_id": robot_id, "available": False, "reason": self.reason, "telemetry": None}
        _, measured, received, telemetry = sample
        age = time.monotonic() - measured
        available = self.reason == "" and age <= MAX_AGE
        return {"robot_id": robot_id, "available": available, "source": "vehicle",
                "received_at": received, "age_sec": age, "stale": not available,
                "reason": None if available else self.reason or "telemetry_stale_or_unknown",
                "telemetry": telemetry}

    async def run(self):
        last_binding = None
        last_diagnostic = None
        while True:
            try:
                with SessionLocal() as db:
                    binding = vehicle_binding(db)
                    exists = db.get(Robot, binding[0]) is not None
                if last_binding and binding != last_binding:
                    self.sample = None
                    get_realtime_store().clear_status(last_binding[0])
                last_binding = binding
                await self.poll(binding, exists)
                # Search route runs are not represented by business task rows.
                context = self.context(binding[0], binding)
                if context["available"]:
                    from .control_leases import control_lease_manager
                    telemetry = context["telemetry"]
                    route = telemetry.get("navigation_task")
                    search = telemetry.get("search")
                    if isinstance(search, dict) and isinstance(route, dict) and route.get("run_id") == search.get("run_id"):
                        if route.get("state") == "paused" and search.get("state") in {"paused", "found"}:
                            await control_lease_manager.observe_run({**search, "state": "paused"})
                    if isinstance(search, dict) and search.get("state") in {"cancelled", "finished", "not_found", "fault"}:
                        await control_lease_manager.observe_run(search)
                    nav = telemetry.get("navigation")
                    if isinstance(nav, dict) and nav.get("state") in {"succeeded", "canceled", "failed"}:
                        await control_lease_manager.observe_run({**nav, "run_id": nav.get("goal_id"), "state": "completed"})
            except Exception:
                self.reason = "vehicle_unavailable"
                if last_binding:
                    get_realtime_store().clear_status(last_binding[0])
                logger.debug("Robot telemetry poll failed", exc_info=True)
            if last_binding:
                diagnostic = (last_binding[0], self.reason)
                if diagnostic != last_diagnostic:
                    diagnostic_emit('gateway.failed' if self.reason else 'gateway.connected',
                                    self.reason or 'vehicle_recovered', module='robot_context',
                                    robot_id=last_binding[0], level='WARN' if self.reason else 'INFO')
                    last_diagnostic = diagnostic
            await asyncio.sleep(1)

    async def poll(self, binding, exists):
        robot_id, url = binding
        store = get_realtime_store()
        if not exists:
            self.reason = "robot_not_bound"
            store.clear_status(robot_id)
            return
        started = time.monotonic()
        try:
            result = await get_robot_gateway(url).get_status(robot_id)
        except Exception:
            self.reason = "vehicle_unavailable"
            store.clear_status(robot_id)
            return
        status = result.get("status")
        age = status.get("ros2_status_age_sec") if isinstance(status, dict) else None
        elapsed = time.monotonic() - started
        if not result.get("ok") or type(age) not in (int, float) or not 0 <= age <= MAX_AGE - elapsed:
            self.reason = "telemetry_stale_or_unknown" if result.get("ok") else "vehicle_unavailable"
            store.clear_status(robot_id)
            return
        data = {key: status.get(key) for key in FIELDS}
        age += elapsed
        measured = time.monotonic() - age
        received = datetime.now(timezone.utc).isoformat()
        # Publish only summary fields to the legacy robot status channel.
        store.set_status(robot_id, {
            **{key: data[key] for key in ("mode", "status", "network", "position", "speed",
                                          "battery", "emergency_stop")},
            "updated_at": time.time() - age,
        })
        self.sample = (binding, measured, received, data)
        self.reason = ""


robot_context_service = RobotContextService()
