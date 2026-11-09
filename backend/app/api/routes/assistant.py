import asyncio
import hashlib
import json
import time
from uuid import UUID, uuid4
from ...core.diagnostic_context import context as diagnostic_context
from ...services.diagnostics import emit as diagnostic_emit
from typing import Literal

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request
from fastapi.responses import PlainTextResponse, StreamingResponse
from pydantic import BaseModel, ConfigDict, Field, StrictBool
from sqlalchemy import or_, select, update
from sqlalchemy.orm import Session

from ..deps import get_current_user, get_db, require_permission
from ...db.session import SessionLocal
from ...models import AssistantConfiguration, AssistantEvent, AssistantExecution, AssistantPlan, AssistantReport, AssistantSession, AssistantTurn, User
from ...services.assistant_execution import confirm, emit_event, execution_view, request_cancellation, step_permission
from ...services.assistant_worker import observe, transition
from ...services.control_leases import control_lease_manager
from ...services.assistant_provider import ProviderUnavailable, configured_provider
from ...services.assistant_tools import ask
from ...services.ops import record_audit
from ...services.incident_reports import markdown

router = APIRouter(prefix="/assistant", tags=["assistant"])


class MessageIn(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    client_id: UUID
    text: str = Field(min_length=1, max_length=2000)


class ConfigurationIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    enabled: StrictBool


class ConfirmIn(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    version: int = Field(ge=1)
    digest: str = Field(pattern=r"^[0-9a-f]{64}$")


class ExecutionActionIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    action: Literal["cancel", "loaded", "handover", "continue_plan", "resume"]
    version: int | None = Field(default=None, ge=1)


def session_for(db, session_id, user):
    session = db.get(AssistantSession, session_id)
    if session is None or session.user_id != user.id:
        raise HTTPException(404, "会话不存在")
    return session


def turn_view(turn, user):
    reply = json.loads(turn.reply) if turn.reply else None
    if reply and reply.get("report_id") and "incidents.read" not in user.permissions:
        reply = {"text": "当前账号无权读取此异常报告。", "plan": reply.get("plan")}
    return {"id": turn.id, "client_id": turn.client_id, "text": turn.prompt,
            "reply": reply}


@router.get("/sessions")
def sessions(db: Session = Depends(get_db), user: User = Depends(require_permission("assistant.read"))):
    rows = db.scalars(select(AssistantSession).where(AssistantSession.user_id == user.id)
                      .order_by(AssistantSession.created_at.desc()).limit(50)).all()
    return {"items": [{"id": row.id, "created_at": row.created_at} for row in rows]}


@router.post("/sessions", status_code=201)
def create_session(db: Session = Depends(get_db), user: User = Depends(require_permission("assistant.use"))):
    item = AssistantSession(id=str(uuid4()), user_id=user.id)
    db.add(item)
    db.commit()
    return {"id": item.id}


@router.get("/sessions/{session_id}/messages")
def messages(session_id: str, db: Session = Depends(get_db),
             user: User = Depends(require_permission("assistant.read"))):
    session_for(db, session_id, user)
    rows = db.scalars(select(AssistantTurn).where(AssistantTurn.session_id == session_id)
                      .order_by(AssistantTurn.created_at.desc(), AssistantTurn.id.desc()).limit(50)).all()
    items = [turn_view(row, user) for row in reversed(rows)]
    drafts = [item["reply"]["plan"] for item in items if item["reply"] and item["reply"].get("plan")]
    if drafts:
        current = dict(db.execute(select(AssistantPlan.id, AssistantPlan.state).where(
            AssistantPlan.session_id == session_id, AssistantPlan.id.in_([draft["id"] for draft in drafts])
        )).all())
        executions = {row.plan_id: execution_view(row) for row in db.scalars(select(AssistantExecution).where(
            AssistantExecution.user_id == user.id, AssistantExecution.plan_id.in_(current)
        ))}
        for draft in drafts:
            state = current.get(draft["id"], "expired")
            draft["state"] = "expired" if state == "draft" and draft["expires_at"] <= int(time.time()) else state
            if draft["id"] in executions:
                draft["execution"] = executions[draft["id"]]
    return {"items": items}


@router.post("/sessions/{session_id}/messages")
async def send_message(session_id: str, payload: MessageIn, db: Session = Depends(get_db),
                       user: User = Depends(require_permission("assistant.use"))):
    session_for(db, session_id, user)
    client_id, owner = str(payload.client_id), user.id
    lookup = select(AssistantTurn).where(AssistantTurn.session_id == session_id, AssistantTurn.client_id == client_id)
    prior = db.scalar(lookup)
    if prior is not None:
        if prior.prompt != payload.text:
            raise HTTPException(409, "重复请求不能修改消息")
        if prior.reply:
            return turn_view(prior, user)
    config = db.get(AssistantConfiguration, 1)
    if config is None or not config.enabled:
        raise HTTPException(503, "助手尚未启用，请联系管理员")
    try:
        provider = configured_provider()
    except ProviderUnavailable as exc:
        raise HTTPException(503, str(exc)) from None
    token, now = str(uuid4()), int(time.time())
    claim = db.execute(update(AssistantSession).where(
        AssistantSession.id == session_id, AssistantSession.user_id == owner,
        or_(AssistantSession.turn_key.is_(None), AssistantSession.turn_until <= now),
    ).values(turn_key=token, turn_until=now + 45))
    if claim.rowcount != 1:
        raise HTTPException(409, "此会话正在处理另一条消息")
    turn = db.scalar(lookup)
    if turn is not None and (turn.reply or turn.prompt != payload.text):
        db.rollback()
        if turn.prompt != payload.text:
            raise HTTPException(409, "重复请求不能修改消息")
        return turn_view(turn, user)
    if turn is None:
        turn = AssistantTurn(id=str(uuid4()), session_id=session_id, client_id=client_id, prompt=payload.text,
                             trace_id=diagnostic_context.get().get('trace_id'))
        db.add(turn)
    history = []
    previous = db.scalars(select(AssistantTurn).where(
        AssistantTurn.session_id == session_id, AssistantTurn.reply.is_not(None)
    ).order_by(AssistantTurn.created_at.desc()).limit(6)).all()
    for row in reversed(previous):
        history.extend([{"role": "user", "content": row.prompt},
                        {"role": "assistant", "content": turn_view(row, user)["reply"]["text"][:2000]}])
    db.commit()
    try:
        try:
            answer, draft, report = await ask(provider, db, user, history, payload.text)
        except (ProviderUnavailable, TimeoutError, ValueError, KeyError, TypeError, AttributeError):
            raise HTTPException(502, "模型暂未返回有效答复，可以重试原消息") from None
        db.expire_all()
        if not user.active or "assistant.use" not in user.permissions:
            raise HTTPException(403, "助手权限已变化")
        finish = db.execute(update(AssistantSession).where(
            AssistantSession.id == session_id, AssistantSession.turn_key == token
        ).values(turn_key=None, turn_until=0))
        if finish.rowcount != 1:
            raise HTTPException(409, "消息处理已过期，请重试")
        result = {"text": answer, "plan": None}
        if report is not None:
            if "incidents.read" not in user.permissions:
                raise HTTPException(403, "异常读取权限已变化")
            item = AssistantReport(id=str(uuid4()), session_id=session_id,
                                   content=json.dumps(report, ensure_ascii=False, allow_nan=False))
            db.add(item)
            result["report_id"] = item.id
        if draft is not None:
            encoded = json.dumps(draft, sort_keys=True, ensure_ascii=False, allow_nan=False)
            plan = AssistantPlan(id=str(uuid4()), session_id=session_id, robot_id=draft["robot_id"], content=encoded,
                                 digest=hashlib.sha256(encoded.encode()).hexdigest(), expires_at=int(time.time())+300,
                                 trace_id=diagnostic_context.get().get('trace_id'))
            db.add(plan)
            result["plan"] = {"id": plan.id, "digest": plan.digest, "version": 1, "state": "draft",
                              "expires_at": plan.expires_at, **draft}
            emit_event(db, owner, "plan.confirmation_required",
                       {"id": plan.id, "session_id": session_id, "expires_at": plan.expires_at})
        turn.reply = json.dumps(result, ensure_ascii=False)
        db.commit()
        if draft is not None:
            diagnostic_emit('assistant.plan', 'draft_created', module='assistant', robot_id=plan.robot_id,
                            details={'plan_id': plan.id, 'version': plan.version})
        return turn_view(turn, user)
    finally:
        db.rollback()
        db.execute(update(AssistantSession).where(
            AssistantSession.id == session_id, AssistantSession.turn_key == token
        ).values(turn_key=None, turn_until=0))
        db.commit()


@router.get("/settings")
def settings(db: Session = Depends(get_db), _: User = Depends(require_permission("assistant.settings"))):
    item = db.get(AssistantConfiguration, 1)
    try:
        configured_provider()
        configured = True
    except ProviderUnavailable:
        configured = False
    return {"enabled": bool(item and item.enabled), "configured": configured}


def plan_for(db, plan_id, user):
    plan = db.get(AssistantPlan, plan_id)
    if plan is None:
        raise HTTPException(404, "计划不存在")
    session_for(db, plan.session_id, user)
    return plan


@router.get("/plans/{plan_id}")
def plan_detail(plan_id: str, db: Session = Depends(get_db),
                user: User = Depends(require_permission("assistant.read"))):
    plan = plan_for(db, plan_id, user)
    execution = db.scalar(select(AssistantExecution).where(AssistantExecution.plan_id == plan_id))
    return {"id": plan.id, "digest": plan.digest, "version": plan.version,
            "state": "expired" if plan.state == "draft" and plan.expires_at <= int(time.time()) else plan.state,
            "expires_at": plan.expires_at, **json.loads(plan.content),
            **({"execution": execution_view(execution)} if execution is not None else {})}


@router.post("/plans/{plan_id}/confirm")
async def confirm_plan(plan_id: str, payload: ConfirmIn, db: Session = Depends(get_db),
                       user: User = Depends(require_permission("assistant.use"))):
    plan = plan_for(db, plan_id, user)
    ids = diagnostic_context.get()
    token = diagnostic_context.set({**ids, 'trace_id': plan.trace_id or ids.get('trace_id')})
    try:
        result = await confirm(db, plan, user, payload.version, payload.digest)
        diagnostic_emit('assistant.confirm', 'plan_confirmed', module='assistant', robot_id=plan.robot_id,
                        execution_id=result.get('id'), details={'plan_id': plan.id, 'version': payload.version})
        return result
    except HTTPException as exc:
        diagnostic_emit('assistant.confirm', 'plan_rejected', module='assistant', level='WARN',
                        details={'plan_id': plan.id, 'status_code': exc.status_code})
        raise
    finally:
        diagnostic_context.reset(token)


@router.post("/plans/{plan_id}/trial-authorize")
def authorize_plan_trial(plan_id: str, payload: ConfirmIn, db: Session = Depends(get_db),
                         user: User = Depends(require_permission("assistant.settings"))):
    from ...services.assistant_trials import authorize_trial
    return authorize_trial(db, user, plan_for(db, plan_id, user), payload.version, payload.digest)


@router.post("/plans/{plan_id}/refresh")
async def refresh_plan(plan_id: str, payload: ConfirmIn, db: Session = Depends(get_db),
                       user: User = Depends(require_permission("assistant.use"))):
    from ...services import assistant_tools
    from ...services.robot_context import vehicle_binding
    original = plan_for(db, plan_id, user)
    if original.version != payload.version or original.digest != payload.digest:
        raise HTTPException(409, "原计划内容或版本已变化")
    execution = db.scalar(select(AssistantExecution).where(AssistantExecution.plan_id == plan_id))
    if execution is not None and execution.state not in {"completed","cancelled","failed"}:
        raise HTTPException(409, "请先结束原执行，再重新生成草案")
    binding = vehicle_binding(db)
    if binding[0] != original.robot_id:
        raise HTTPException(409, "实车绑定已变化")
    if hashlib.sha256(original.content.encode()).hexdigest() != original.digest:
        raise HTTPException(409, "原计划内容摘要不匹配")
    schemas = dict(navigate=assistant_tools.Navigate, patrol=assistant_tools.Patrol,
                   deliver=assistant_tools.Deliver, observe_target=assistant_tools.Observe,
                   patrol_search=assistant_tools.PatrolSearch, move_relative=assistant_tools.MoveRelative)
    steps = json.loads(original.content)["steps"]
    proposal = assistant_tools.Proposal(steps=[
        {key:value for key,value in step.items() if key in schemas[step["action"]].model_fields}
        for step in steps])
    draft = await assistant_tools.propose(db, user, binding, proposal)
    content = json.dumps(draft, sort_keys=True, ensure_ascii=False, allow_nan=False)
    row = AssistantPlan(id=str(uuid4()),session_id=original.session_id,robot_id=binding[0],content=content,
                        digest=hashlib.sha256(content.encode()).hexdigest(),expires_at=int(time.time())+300)
    db.add(row);db.flush()
    view = {"id":row.id,"version":row.version,"digest":row.digest,"state":"draft",
            "expires_at":row.expires_at,**draft}
    db.add(AssistantTurn(id=str(uuid4()),session_id=row.session_id,client_id=str(uuid4()),
        prompt="重新核验上一份任务",
        reply=json.dumps({"text":"已重新核验原任务的资源和能力，未重新调用模型，等待再次确认。",
                          "plan":view},ensure_ascii=False)))
    emit_event(db,user.id,"plan.confirmation_required",{"id":row.id,"session_id":row.session_id,"expires_at":row.expires_at})
    record_audit(db,user,"assistant.plan.refresh","assistant_plan",row.id,after={"source_plan_id":plan_id})
    db.commit()
    return plan_detail(row.id,db,user)


@router.get("/executions/{execution_id}")
def get_execution(execution_id: str, db: Session = Depends(get_db),
                  user: User = Depends(require_permission("assistant.read"))):
    execution = db.get(AssistantExecution, execution_id)
    if execution is None or execution.user_id != user.id:
        raise HTTPException(404, "执行记录不存在")
    return execution_view(execution)


@router.get("/reports/{report_id}")
def get_report(report_id: str, format: Literal["json", "markdown"] = "json", db: Session = Depends(get_db),
               user: User = Depends(require_permission("assistant.read"))):
    if "incidents.read" not in user.permissions:
        raise HTTPException(403, "缺少异常读取权限")
    item = db.get(AssistantReport, report_id)
    if item is None:
        raise HTTPException(404, "报告不存在")
    session_for(db, item.session_id, user)
    report = json.loads(item.content)
    if format == "markdown":
        return PlainTextResponse(markdown(report), media_type="text/markdown",
                                 headers={"Content-Disposition": f'attachment; filename="insightrover-{item.id}.md"'})
    return {"id": item.id, **report}


@router.post("/executions/{execution_id}/actions")
async def execution_action(execution_id: str, payload: ExecutionActionIn, db: Session = Depends(get_db),
                           user: User = Depends(require_permission("assistant.use"))):
    execution = db.get(AssistantExecution, execution_id)
    if execution is None or execution.user_id != user.id:
        raise HTTPException(404, "执行记录不存在")
    if payload.action == "cancel":
        if execution.state in {"cancelled", "cancel_requested"}:
            return execution_view(execution)
        rows = request_cancellation(db, execution_id=execution_id, user_id=user.id)
        if not rows:
            raise HTTPException(409, "当前执行阶段无法取消，请核对车辆状态")
        result = execution_view(rows[0])
        run_id = rows[0].run_id
        record_audit(db, user, "assistant.cancel", "assistant_execution", execution_id)
        db.commit()
        if run_id:
            await control_lease_manager.release_run(run_id)
        return result
    if payload.version != execution.version:
        raise HTTPException(409, "执行状态已变化，请刷新")
    plan = plan_for(db, execution.plan_id, user)
    steps = json.loads(plan.content)["steps"]
    if execution.step_index >= len(steps):
        raise HTTPException(409, "计划已结束")
    step_permission(user, steps[execution.step_index]["action"])
    expected = {"loaded": "waiting_load", "handover": "waiting_handover", "continue_plan": "found"}
    if payload.action == "resume" and execution.state == "paused":
        phase = execution.vehicle_state
        if not execution.run_id:
            row = transition(db, execution, payload.version, "queued", message=None)
        elif phase in {"completed", "not_found", "finished", "waiting_load", "waiting_handover", "found"}:
            row = observe(db, execution, payload.version, {"state": phase}, len(steps))
        elif phase in {"prepared", "paused"}:
            row = transition(db, execution, payload.version, "action_pending",
                             pending_action="start" if phase == "prepared" else "resume", message=None)
        else:
            raise HTTPException(409, "尚未核实可恢复的车端状态")
    elif execution.state == "waiting_human" and expected.get(payload.action) == execution.vehicle_state:
        row = transition(db, execution, payload.version, "action_pending", pending_action=payload.action)
    else:
        raise HTTPException(409, "当前阶段不允许此操作")
    if row is None:
        raise HTTPException(409, "执行状态已变化，请刷新")
    return execution_view(row)


def event_batch(authorization, after):
    with SessionLocal() as db:
        user = get_current_user(authorization, db)
        if "assistant.read" not in user.permissions:
            raise HTTPException(403, "缺少助手读取权限")
        rows = db.scalars(select(AssistantEvent).where(
            AssistantEvent.user_id == user.id, AssistantEvent.id > after
        ).order_by(AssistantEvent.id).limit(100)).all()
        return [(row.id, {"kind": row.kind, "payload": json.loads(row.payload)}) for row in rows]


@router.get("/events")
async def events(request: Request, after: int = Query(default=0, ge=0, le=2**53-1),
                 authorization: str | None = Header(default=None)):
    initial = await asyncio.to_thread(event_batch, authorization, after)

    async def stream():
        cursor, batch = after, initial
        until = time.monotonic() + 25
        while time.monotonic() < until and not await request.is_disconnected():
            for cursor, value in batch:
                data = json.dumps(value, ensure_ascii=False)
                yield f"id: {cursor}\ndata: {data}\n\n"
            if not batch:
                yield ": keepalive\n\n"
                await asyncio.sleep(1)
            try:
                batch = await asyncio.to_thread(event_batch, authorization, cursor)
            except HTTPException:
                return

    return StreamingResponse(stream(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


@router.put("/settings")
def set_settings(payload: ConfigurationIn, db: Session = Depends(get_db),
                 user: User = Depends(require_permission("assistant.settings"))):
    if payload.enabled:
        try:
            configured_provider()
        except ProviderUnavailable as exc:
            raise HTTPException(409, str(exc)) from None
    item = db.get(AssistantConfiguration, 1)
    if item is None:
        item = AssistantConfiguration(id=1, enabled=payload.enabled)
        db.add(item)
    item.enabled = payload.enabled
    record_audit(db, user, "assistant.settings", "assistant", after={"enabled": payload.enabled})
    db.commit()
    return settings(db, user)
