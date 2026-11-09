"""Reconcile persisted tasks using read-only vehicle requests."""
import asyncio
import logging

from sqlalchemy import select

from ..db.session import SessionLocal
from ..gateway import get_robot_gateway
from ..models import MissionTask, PatrolTask
from .navigation_execution import execution, store_execution
from .robot_context import vehicle_binding
from .control_leases import control_lease_manager
from .diagnostics import emit as diagnostic_emit

logger = logging.getLogger(__name__)
TERMINAL = {"completed", "cancelled", "failed"}
VEHICLE_STATES = TERMINAL | {
    "prepared", "waiting_load", "planning", "running", "returning",
    "dwelling", "paused", "waiting_handover",
}


async def reconcile_once(session_factory=SessionLocal):
    with session_factory() as db:
        binding = vehicle_binding(db)
        pending = []
        for model in (MissionTask, PatrolTask):
            tasks = db.scalars(select(model).where(
                model.robot_id == binding[0], model.status.notin_(TERMINAL)
            )).all()
            for task in tasks:
                previous = execution(task)
                if previous and previous.get("run_id") and previous.get("state") not in TERMINAL:
                    pending.append((model, task.id, previous["run_id"]))
    gateway = get_robot_gateway(binding[1])
    for model, task_id, run_id in pending:
        try:
            value = await gateway.navigation_request("task", query={"run_id": run_id})
            if (not isinstance(value, dict) or value.get("run_id") != run_id
                    or value.get("task_id") != task_id or value.get("state") not in VEHICLE_STATES):
                continue
            with session_factory() as db:
                # A changed physical binding invalidates in-flight replies.
                if vehicle_binding(db) != binding:
                    return
                task = db.get(model, task_id)
                if task is None or task.robot_id != binding[0]:
                    continue
                previous = execution(task)
                if not previous or previous.get("run_id") != run_id:
                    continue
                store_execution(db, task, value)
                db.commit()
                accepted = execution(task)
                if accepted and accepted.get('state') != previous.get('state'):
                    diagnostic_emit('task.changed', accepted['state'], module='task_reconciler',
                                    robot_id=binding[0], task_id=task_id, run_id=run_id,
                                    level='WARN' if accepted['state'] == 'failed' else 'INFO',
                                    details={'state': accepted['state']})
            await control_lease_manager.observe_run(accepted)
        except Exception:
            logger.debug("Vehicle task reconciliation pending for %s", task_id, exc_info=True)


async def run_task_reconciler():
    while True:
        try:
            await reconcile_once()
        except Exception:
            logger.debug("Task reconciliation unavailable", exc_info=True)
        await asyncio.sleep(1)
