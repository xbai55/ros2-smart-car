"""Deterministic sequential executor for confirmed plans."""
import asyncio
import hashlib
import json
import logging
import math
import time
from uuid import NAMESPACE_URL, uuid4, uuid5

from fastapi import HTTPException
from sqlalchemy import or_, select, update
from sqlalchemy.exc import IntegrityError

from ..api.routes import navigation_tasks
from ..db.session import SessionLocal
from ..gateway import get_robot_gateway
from ..models import AssistantExecution, AssistantPlan, AssistantTrialAuthorization, AssistantWorkerLock, User
from ..core.diagnostic_context import context as diagnostic_context
from .diagnostics import emit as diagnostic_emit
from .assistant_execution import emit_event, execution_view, request_cancellation, step_permission, validate_steps
from .control_leases import control_lease_manager
from .robot_context import robot_context_service, vehicle_binding
from .search_execution import execute_search, SearchRequestRejected

logger = logging.getLogger(__name__)
TERMINAL = {"completed", "cancelled", "failed"}
ACTIVE = {"queued", "dispatching", "unconfirmed", "running", "waiting_human", "paused", "action_pending"}


def transition(db, row, version, state, **changes):
    previous_run = row.run_id
    result = db.execute(update(AssistantExecution).where(
        AssistantExecution.id == row.id, AssistantExecution.version == version
    ).values(state=state, version=version + 1, **changes).returning(AssistantExecution))
    current = result.scalar_one_or_none()
    if current is not None:
        value = {**execution_view(current), 'run_id': current.run_id or previous_run}
        if state == "waiting_human":
            value["session_id"] = db.get(AssistantPlan, current.plan_id).session_id
        emit_event(db, current.user_id, "execution." + state, value)
    db.commit()
    if current is not None and state in {'failed', 'paused'} and changes.get('message'):
        from .system_health import observe_problems
        code = 'task.' + current.id
        observe_problems(db, current.robot_id, {code: {'code': code, 'message': '任务停止或执行失败',
            'impact': '任务未完成，需核对执行记录', 'suggestion': '查看本次任务诊断链路',
            'execution_id': current.id, 'status': 'observed', 'root_cause_confirmed': False}}, immediate=True)
    if current is not None:
        diagnostic_emit('assistant.execution', state, module='assistant_worker',
                        execution_id=current.id, robot_id=current.robot_id, run_id=value['run_id'], task_id=current.task_id,
                        details={'state': state, 'version': current.version, 'step_index': current.step_index})
    return current


def _advance(db, row, version, step_count, message=None):
    pickup = row.phase == "pickup"
    index = row.step_index if pickup else row.step_index + 1
    return transition(db, row, version, "queued" if index < step_count else "completed",
                      step_index=index, phase="delivery" if pickup else "step", run_id=None,
                      task_id=None, run_kind=None, vehicle_address=None, vehicle_state=None,
                      pending_action=None, message=message)


def observe(db, row, version, result, step_count):
    phase = result["state"]
    if row.run_kind == "search" and phase in {"finished", "not_found"}:
        context = robot_context_service.context(row.robot_id, (row.robot_id, row.vehicle_address))
        lock = (context.get("telemetry") or {}).get("search_control") or {}
        if not context["available"] or lock.get("run_id") != row.run_id or lock.get("active") is not False:
            if row.state == "running" and row.vehicle_state == phase:
                return row
            return transition(db, row, version, "running", vehicle_state=phase,
                              pending_action=None, message="等待车端确认搜索停车锁已释放")
    if phase in {"completed", "not_found"} or (row.run_kind == "search" and phase == "finished"):
        return _advance(db, row, version, step_count, result.get("message") if row.run_kind == "relative" else None)
    if phase in {"waiting_load", "waiting_handover", "found"}:
        state = "waiting_human"
    elif phase in {"failed", "cancelled", "fault", "paused"}:
        state = "paused"
    elif phase in {"planning", "running", "returning", "dwelling", "preparing", "searching", "stopping"}:
        state = "running"
    else:
        state = "paused"
    if state == row.state and phase == row.vehicle_state:
        return row
    return transition(db, row, version, state, vehicle_state=phase, pending_action=None,
                      message=str(result.get("message") or "")[:500])


def _waypoints(result):
    return {key: result[key] for key in ("map_key", "control_session_id", "calibration_matrix",
                                         "calibration_drawing", "waypoints")}


async def lookup_run(db, row, user):
    if row.run_kind == "relative":
        # A host restart must never replay an uncertain relative displacement.
        return {"run_id":row.run_id,"state":"failed","message":"短距动作中断后不自动重放，请重新生成计划"}
    if row.run_kind == "search":
        result = await get_robot_gateway(row.vehicle_address).search_request(row.run_id)
    else:
        result = await navigation_tasks.get_execution(row.run_kind, row.task_id, db, user)
    if not result or result.get("run_id") != row.run_id:
        raise RuntimeError("车端运行记录未确认")
    return result


def _plan_steps(plan):
    if plan.state != "confirmed" or hashlib.sha256(plan.content.encode()).hexdigest() != plan.digest:
        raise HTTPException(409, "计划内容已变化")
    steps = json.loads(plan.content)["steps"]
    if not 1 <= len(steps) <= 6:
        raise HTTPException(409, "计划步骤数无效")
    return steps


class AssistantWorker:
    def __init__(self, session_factory=SessionLocal):
        self.sessions = session_factory
        self.owner = str(uuid4())
        self.initialized = False

    def acquire_worker(self):
        with self.sessions() as db:
            now = int(time.time())
            if db.get(AssistantWorkerLock, 1) is None:
                db.add(AssistantWorkerLock(id=1, owner=self.owner, expires_at=0))
                try:
                    db.commit()
                except IntegrityError:
                    db.rollback()
            claimed = db.execute(update(AssistantWorkerLock).where(
                AssistantWorkerLock.id == 1, or_(AssistantWorkerLock.owner == self.owner,
                                                AssistantWorkerLock.expires_at <= now)
            ).values(owner=self.owner, expires_at=now + 60)).rowcount == 1
            db.commit()
            return claimed

    def recover(self):
        with self.sessions() as db:
            lock = db.get(AssistantWorkerLock, 1)
            if lock is None or lock.owner != self.owner:
                return
            rows = db.scalars(select(AssistantExecution).where(AssistantExecution.state.in_(ACTIVE))).all()
            for row in rows:
                transition(db, row, row.version, "paused", pending_action=None,
                           message="主机重启，已停止自动推进，请核对车端后恢复")

    def guard(self, ident, version, generation, step):
        with self.sessions() as db:
            lock, row = db.get(AssistantWorkerLock, 1), db.get(AssistantExecution, ident)
            if (lock is None or lock.owner != self.owner or lock.expires_at <= int(time.time())
                    or row is None or row.version != version or row.state != "dispatching"
                    or control_lease_manager.generation != generation):
                raise HTTPException(409, "执行已取消或控制权已变化")
            user = db.get(User, row.user_id)
            if user is None or not user.active:
                raise HTTPException(403, "账号已停用")
            step_permission(user, step["action"])
            if db.get(AssistantTrialAuthorization, row.plan_id):
                from .assistant_trials import require_trial
                require_trial(db, user, row.plan_id, step["action"], step["capability"]["fingerprint"], row.id)
            permissions = {"maps.read"} if step["resources"] else set()
            if any(resource["reference"]["source"] == "business_route" for resource in step["resources"]):
                permissions.add("routes.read")
            if not permissions <= user.permissions:
                raise HTTPException(403, "资源读取权限已变化")

    async def _dispatch(self, db, row, user, step, count):
        ident, version = row.id, row.version
        generation = control_lease_manager.generation
        trial = db.get(AssistantTrialAuthorization, row.plan_id)
        trial_args = {"trial_plan": row.plan_id, "trial_execution": row.id} if trial else {}
        binding, resolved = await validate_steps(db, user, row.robot_id, [step], **trial_args)
        action = step["action"]
        phase = "pickup" if action == "deliver" and row.phase == "step" else row.phase
        kind = "relative" if action == "move_relative" else "search" if action in {"patrol_search", "observe_target"} else "delivery" if phase == "delivery" else "patrol"
        run_id = str(uuid5(NAMESPACE_URL, f"assistant:{ident}:{row.step_index}:{phase}"))
        task_id = str(uuid5(NAMESPACE_URL, f"navigation:{kind}:{run_id}")) if kind not in {"search","relative"} else None
        row = transition(db, row, version, "dispatching", run_id=run_id, run_kind=kind,
                         task_id=task_id, phase=phase, vehicle_address=binding[1], message=None)
        if row is None:
            return
        version += 1

        def guard():
            self.guard(ident, version, generation, step)

        guard()
        if kind == "relative":
            from .relative_motion import execute_relative
            result = await execute_relative(binding, user, step, run_id, guard)
            guard()
        elif kind == "search":
            wire = {"run_id": run_id, "travel": "stationary" if action == "observe_target" else "patrol",
                    "targets": [{"name": step["target"]}]}
            if action == "patrol_search":
                wire["patrol"] = _waypoints(resolved[0][0])
            result = await execute_search(db, binding, user, "start", wire, guard=guard,
                **({"trial_context": (row.plan_id, row.id)} if trial else {}))
        else:
            index = 1 if phase == "delivery" else 0
            wire = {**_waypoints(resolved[0][index]), "robot_id": row.robot_id, "kind": kind, "run_id": run_id,
                    "map_id": step["resources"][index]["reference"]["map_id"] if
                    step["resources"][index]["reference"]["source"] != "vehicle_place" else None,
                    "name": "助手取件导航" if phase == "pickup" else "助手文件运输" if phase == "delivery" else "助手导航任务",
                    "return_to_start": False, "cycles": 1}
            if phase == "delivery":
                wire.update(cargo=step["cargo"], pickup_name=resolved[0][0]["waypoints"][0]["name"])
            result = await navigation_tasks.create_execution(wire, db, user)
            if kind == "patrol" and result["state"] == "prepared":
                result = await navigation_tasks.apply_execution_action(kind, task_id, {
                    "action": "start", "run_id": run_id}, db, user, guard=guard)
        observe(db, row, version, result, count)

    async def _human_action(self, db, row, user, step, count):
        ident, version, action = row.id, row.version, row.pending_action
        if row.run_kind == "relative":
            raise HTTPException(409, "短距动作不可恢复或重放，请取消后重新生成计划")
        generation = control_lease_manager.generation
        if vehicle_binding(db) != (row.robot_id, row.vehicle_address):
            raise HTTPException(409, "实车绑定已变化")
        if action in {"loaded", "start", "resume"}:
            await validate_steps(db, user, row.robot_id, [step])
        row = transition(db, row, version, "dispatching")
        if row is None:
            return
        version += 1

        def guard():
            self.guard(ident, version, generation, step)

        guard()
        if row.run_kind == "search":
            result = await execute_search(db, vehicle_binding(db), user, "action",
                                          {"run_id": row.run_id, "action": action if action in {"resume", "pause"} else "finish"}, guard=guard)
        else:
            result = await navigation_tasks.apply_execution_action(row.run_kind, row.task_id, {
                "run_id": row.run_id, "action": action}, db, user, guard=guard)
        observe(db, row, version, result, count)

    async def tick(self):
        with self.sessions() as db:
            # The oldest unfinished plan holds its place while waiting for a human.
            row = db.scalar(select(AssistantExecution).where(
                AssistantExecution.state.notin_(TERMINAL)
            ).order_by(AssistantExecution.created_at, AssistantExecution.id).limit(1))
            if row is None:
                return
            ident, initial_version = row.id, row.version
            diagnostic_plan = db.get(AssistantPlan, row.plan_id)
            token = diagnostic_context.set({'trace_id': getattr(diagnostic_plan, 'trace_id', None),
                                            'execution_id': row.id, 'robot_id': row.robot_id,
                                            'run_id': row.run_id})
            try:
                if row.state == "cancel_requested":
                    await self._cancel_run(db, row)
                    return
                plan, user = db.get(AssistantPlan, row.plan_id), db.get(User, row.user_id)
                if plan is None or user is None or not user.active:
                    raise HTTPException(403, "账号或已确认计划不可用")
                steps = _plan_steps(plan)
                step = steps[row.step_index]
                step_permission(user, step["action"])
                if db.get(AssistantTrialAuthorization, row.plan_id):
                    from .assistant_trials import require_trial
                    try:
                        require_trial(db, user, row.plan_id, step["action"], step["capability"]["fingerprint"], row.id)
                    except HTTPException:
                        row = transition(db, row, row.version, "cancel_requested",
                                         message="现场测试授权失效，正在结束本次任务")
                        if row:
                            await self._cancel_run(db, row)
                        return
                if row.state == "queued":
                    if row.step_index == 0 and row.phase == "step" and plan.expires_at <= int(time.time()):
                        raise HTTPException(409, "首步等待超时，请重新确认")
                    await self._dispatch(db, row, user, step, len(steps))
                elif row.state == "action_pending":
                    await self._human_action(db, row, user, step, len(steps))
                elif row.run_id and row.state in {"running", "unconfirmed", "paused"}:
                    if vehicle_binding(db) != (row.robot_id, row.vehicle_address):
                        raise HTTPException(409, "实车绑定已变化")
                    result = await lookup_run(db, row, user)
                    if row.state == "running":
                        observe(db, row, initial_version, result, len(steps))
                    elif row.state == "unconfirmed" or row.vehicle_state != result["state"]:
                        transition(db, row, initial_version, "paused", vehicle_state=result["state"],
                                   message="已核对车端记录，等待人工决定")
            except Exception as exc:
                db.rollback()
                current = db.get(AssistantExecution, ident)
                if current and current.version in {initial_version, initial_version + 1}:
                    if current.state == 'dispatching' and isinstance(exc, SearchRequestRejected):
                        if current.run_id:
                            await control_lease_manager.release_run(current.run_id)
                        transition(db, current, current.version, 'failed', message=exc.detail)
                    elif current.state == "dispatching":
                        if current.run_id:
                            await control_lease_manager.release_run(current.run_id)
                        transition(db, current, current.version, "unconfirmed",
                                   message="派发状态待核实，后续步骤已暂停")
                    elif current.state in {"queued", "action_pending", "running", "waiting_human"}:
                        if current.run_id:
                            await control_lease_manager.release_run(current.run_id)
                        transition(db, current, current.version, "paused",
                                   message=exc.detail if isinstance(exc, HTTPException) and isinstance(exc.detail, str)
                                   else "车辆或执行状态未确认")
                diagnostic_emit('assistant.execution', 'reconciliation_required', module='assistant_worker',
                                level='ERROR', exception=exc)
                logger.debug("Assistant execution requires reconciliation for %s", ident, exc_info=True)
            finally:
                diagnostic_context.reset(token)

    async def _cancel_run(self, db, row):
        version = row.version
        if row.run_id:
            gateway = get_robot_gateway(row.vehicle_address)
            if row.run_kind == "relative":
                manager = control_lease_manager
                lease = manager.current
                if lease and lease.run_id == row.run_id:
                    try:
                        result = await gateway.stop()
                    finally:
                        await manager.release_run(row.run_id, lease=lease)
                    if result.get("stationary_confirmed") is not True:
                        return
                else:
                    status = await gateway.get_status(row.robot_id)
                    telemetry = status.get("status") or {}
                    odom = telemetry.get("odom") or {}
                    if (not status.get("ok") or odom.get("ok") is not True
                            or type(odom.get("odom_age_sec")) not in (int,float) or not 0 <= odom["odom_age_sec"] < .5
                            or type(odom.get("linear_speed_xy")) not in (int,float)
                            or not math.isfinite(odom["linear_speed_xy"])
                            or abs(odom["linear_speed_xy"]) >= .01
                            or type(odom.get("angular_speed")) not in (int,float)
                            or not math.isfinite(odom["angular_speed"]) or abs(odom["angular_speed"]) >= .02):
                        return
                result = {"run_id":row.run_id,"state":"cancelled"}
            elif row.run_kind == "search":
                result = await gateway.search_request(row.run_id, operation="action", payload={"action": "cancel"})
            else:
                result = await gateway.navigation_request("task/action", {
                    "action": "cancel", "run_id": row.run_id, "task_id": row.task_id, "kind": row.run_kind})
            if result.get("run_id") != row.run_id or result.get("state") not in {"cancelled", "completed", "finished", "failed", "not_found"}:
                return
            await control_lease_manager.release_run(row.run_id)
        transition(db, row, version, "cancelled", pending_action=None, message="计划已取消")

    async def run(self):
        try:
            while True:
                try:
                    if self.acquire_worker():
                        if not self.initialized:
                            self.recover()
                            self.initialized = True
                        async with asyncio.timeout(45):
                            await self.tick()
                    else:
                        self.initialized = False
                except Exception:
                    self.initialized = False
                    logger.exception("Assistant executor tick failed")
                await asyncio.sleep(1)
        finally:
            if self.initialized:
                self.recover()
            with self.sessions() as db:
                db.execute(update(AssistantWorkerLock).where(AssistantWorkerLock.owner == self.owner).values(expires_at=0))
                db.commit()


async def cancel_on_desktop_exit():
    worker = AssistantWorker()
    with worker.sessions() as db:
        robot_id, _ = vehicle_binding(db)
        request_cancellation(db, robot_id=robot_id)
        db.commit()
        rows = db.scalars(select(AssistantExecution).where(
            AssistantExecution.robot_id == robot_id, AssistantExecution.state == "cancel_requested"
        ).order_by(AssistantExecution.created_at)).all()
        try:
            async with asyncio.timeout(3):
                for row in rows:
                    await worker._cancel_run(db, row)
        except Exception:
            # A restart will reconcile the durable cancellation against the exact run.
            logger.info("Desktop exited with pending assistant cancellation")
