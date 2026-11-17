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
    from .task_sync import refresh_execution
    for model, task_id, run_id in pending:
        try:
            with session_factory() as db:
                if vehicle_binding(db) != binding:
                    return
                task = db.get(model, task_id)
                if task is None or task.robot_id != binding[0]:
                    continue
                previous = execution(task)
                if not previous or previous.get('run_id') != run_id:
                    continue
                accepted = await refresh_execution(db, task, gateway, binding_guard=lambda:vehicle_binding(db)==binding)
                if accepted and (accepted.get('state'),accepted.get('sync_state')) != (previous.get('state'),previous.get('sync_state')):
                    diagnostic_emit('task.changed', accepted.get('sync_state',accepted['state']),module='task_reconciler',
                                    robot_id=binding[0],task_id=task_id,run_id=run_id,details={'state':accepted['state']})
                await control_lease_manager.observe_run(accepted)
        except Exception:
            logger.debug('Vehicle task reconciliation pending for %s',task_id,exc_info=True)


async def run_task_reconciler():
    while True:
        try:
            await reconcile_once()
        except Exception:
            logger.debug("Task reconciliation unavailable", exc_info=True)
        await asyncio.sleep(1)
