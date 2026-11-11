"""Server-side authorization and version checks for confirmed assistant plans."""
import asyncio
import hashlib
import json
import time
from uuid import uuid4

from fastapi import HTTPException
from sqlalchemy import case, select, update

from ..api.routes import resources
from ..models import AssistantEvent, AssistantExecution, AssistantPlan, Robot
from .assistant_tools import require
from .capabilities import capability_snapshot
from .ops import record_audit
from .robot_context import robot_context_service, vehicle_binding


def emit_event(db, owner, kind, payload):
    if kind.startswith("execution.") and "session_id" not in payload:
        plan = db.get(AssistantPlan, payload["plan_id"])
        if plan is not None:
            payload = {**payload, "session_id": plan.session_id}
    db.add(AssistantEvent(user_id=owner, kind=kind,
                          execution_id=payload.get('id') if kind.startswith('execution.') else None,
                          payload=json.dumps(payload, ensure_ascii=False)))


def execution_view(row):
    return {"id": row.id, "plan_id": row.plan_id, "robot_id": row.robot_id, "state": row.state,
            "step_index": row.step_index, "version": row.version, "vehicle_state": row.vehicle_state,
            "message": row.message}


def request_cancellation(db, *, robot_id=None, execution_id=None, user_id=None):
    conditions = [AssistantExecution.state.in_({"queued", "dispatching", "running", "waiting_human",
                                               "paused", "unconfirmed", "action_pending"})]
    if robot_id is not None:
        conditions.append(AssistantExecution.robot_id == robot_id)
    else:
        conditions.extend([AssistantExecution.id == execution_id, AssistantExecution.user_id == user_id])
    rows = db.scalars(update(AssistantExecution).where(*conditions).values(
        state=case((AssistantExecution.run_id.is_(None), "cancelled"), else_="cancel_requested"),
        pending_action=None, version=AssistantExecution.version + 1,
    ).returning(AssistantExecution)).all()
    for row in rows:
        emit_event(db, row.user_id, "execution." + row.state, execution_view(row))
    return rows


def step_permission(user, action):
    require(user, "assistant.use", "robots.read", "robots.control")
    if action == "deliver":
        require(user, "missions.manage", "missions.read", "patrol.manage", "patrol.read")
    elif action in {"navigate", "patrol", "patrol_search", "observe_target"}:
        require(user, "patrol.manage")
        if action in {"navigate", "patrol"}:
            require(user, "patrol.read")
    elif action != "move_relative":
        raise HTTPException(409, "计划包含未知动作")


async def validate_steps(db, user, robot_id, steps, *, trial_plan=None, trial_execution=None):
    from .assistant_tools import MoveRelative
    if any(step["action"] == "move_relative" for step in steps):
        if len(steps) != 1:
            raise HTTPException(409, "短距离前进只能作为单步计划")
        MoveRelative.model_validate({key: steps[0][key] for key in ("action", "distance_m")})
    binding = vehicle_binding(db)
    if binding[0] != robot_id or db.get(Robot, robot_id) is None:
        raise HTTPException(409, "实车绑定已变化")
    for step in steps:
        step_permission(user, step["action"])
    resolved = []
    async with asyncio.timeout(15):
        for step in steps:
            points = []
            for resource in step["resources"]:
                request = resources.ResolveIn(robot_id=robot_id, references=[resource["reference"]],
                                              expected_version=resource["resource_version"])
                result = await resources.resolve(request, db, user)
                if result["map_key"] != resource["map_key"] or result["resource_version"] != resource["resource_version"]:
                    raise HTTPException(409, "地点、路线或地图版本已变化，请重新生成草案")
                points.append(result)
            resolved.append(points)
    # Re-read binding and permissions after the vehicle network round trips.
    db.expire_all()
    if not user.active:
        raise HTTPException(403, "账号已停用")
    if vehicle_binding(db) != binding:
        raise HTTPException(409, "实车绑定已变化")
    context = robot_context_service.context(robot_id, binding)
    capabilities = capability_snapshot(db, context)["capabilities"]
    for step in steps:
        step_permission(user, step["action"])
        current = capabilities[step["action"]]
        if not current["executable"]:
            if trial_plan is None or not current["supported"] or not current["ready"]:
                raise HTTPException(409, "车辆能力未就绪或当前版本缺少实车验收")
            from .assistant_trials import require_trial
            require_trial(db, user, trial_plan, step["action"], current["fingerprint"], trial_execution)
        if current["fingerprint"] != step["capability"]["fingerprint"]:
            raise HTTPException(409, "车端版本或能力已变化，请重新生成草案")
    return binding, resolved


async def confirm(db, plan, user, version, digest):
    plan_id, robot_id = plan.id, plan.robot_id
    if plan.version != version or plan.digest != digest or hashlib.sha256(plan.content.encode()).hexdigest() != digest:
        raise HTTPException(409, "计划版本或内容已变化")
    previous = db.scalar(select(AssistantExecution).where(AssistantExecution.plan_id == plan_id))
    if previous is not None:
        return execution_view(previous)
    if plan.state != "draft" or plan.expires_at <= int(time.time()):
        raise HTTPException(409, "计划已过期或不可确认")
    steps = json.loads(plan.content)["steps"]
    from ..models import AssistantTrialAuthorization
    trial = db.get(AssistantTrialAuthorization, plan_id)
    try:
        await validate_steps(db, user, robot_id, steps, **({"trial_plan": plan_id} if trial else {}))
    except TimeoutError:
        raise HTTPException(409, "车端核验超时，请重试原计划") from None
    claim = db.execute(update(AssistantPlan).where(
        AssistantPlan.id == plan_id, AssistantPlan.state == "draft",
        AssistantPlan.version == version, AssistantPlan.digest == digest,
        AssistantPlan.expires_at > int(time.time()),
    ).values(state="confirmed"))
    if claim.rowcount != 1:
        previous = db.scalar(select(AssistantExecution).where(AssistantExecution.plan_id == plan_id))
        if previous is not None:
            return execution_view(previous)
        raise HTTPException(409, "计划已过期或已变化")
    row = AssistantExecution(id=str(uuid4()), plan_id=plan_id, robot_id=robot_id, user_id=user.id)
    db.add(row)
    db.flush()
    if trial is not None:
        consumed = db.execute(update(AssistantTrialAuthorization).where(
            AssistantTrialAuthorization.plan_id == plan_id,
            AssistantTrialAuthorization.execution_id.is_(None),
            AssistantTrialAuthorization.expires_at > int(time.time()),
        ).values(execution_id=row.id))
        if consumed.rowcount != 1:
            db.rollback()
            raise HTTPException(409, "单次现场测试授权已消费或已过期")
    result = execution_view(row)
    emit_event(db, user.id, "execution.queued", result)
    record_audit(db, user, "assistant.confirm", "assistant_plan", plan_id,
                 after={"execution_id": row.id, "digest": digest, "version": version})
    db.commit()
    return result
