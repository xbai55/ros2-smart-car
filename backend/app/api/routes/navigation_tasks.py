"""Business tasks use vehicle-confirmed execution records, never optimistic arrival."""
import asyncio
import json
import hashlib
from datetime import datetime, timezone
from uuid import NAMESPACE_URL, uuid4, uuid5

from fastapi import APIRouter, Body, Depends, HTTPException
import httpx
from sqlalchemy.orm import Session

from ...models import MissionTask, PatrolTask, Robot, MapModel, User
from ...gateway import get_robot_gateway
from ...services.ops import json_loads, record_audit
from ...services.tasks import serialize_mission, serialize_patrol
from ..deps import get_db, require_permission
from ...services.robot_context import vehicle_binding
from ...services.navigation_execution import execution, store_execution
from ...services.task_sync import refresh_execution, STATES
from ...services.control_leases import control_lease_manager
from ...services.direct_navigation import navigation_parking
from ...services.diagnostics import emit as diagnostic_emit

router = APIRouter(prefix="/navigation-tasks", tags=["navigation-tasks"])


def _error(code, message):
    return HTTPException(status_code=code, detail={"code": "NAVIGATION_TASK", "message": message})


def _task(db, kind, ident):
    model = MissionTask if kind == "delivery" else PatrolTask if kind == "patrol" else None
    item = db.get(model, ident) if model else None
    if item is None:
        raise _error(404, "任务不存在")
    return item


def _permission(user, kind, manage=True):
    permission = ("missions" if kind == "delivery" else "patrol") + (".manage" if manage else ".read")
    if permission not in user.permissions or (manage and "robots.control" not in user.permissions):
        raise _error(403, "没有此任务的操作权限")


def _gateway(db):
    return get_robot_gateway(vehicle_binding(db)[1])


def _check_binding(db, robot_id):
    if not robot_id or robot_id != vehicle_binding(db)[0]:
        raise _error(409, "任务未分配给当前绑定的实车")


async def _call(db, path, payload=None, query=None, *, gateway=None):
    try:
        return await (gateway or _gateway(db)).navigation_request(path, payload, query=query)
    except httpx.HTTPStatusError as exc:
        try:
            message = str(exc.response.json().get("detail", "车端拒绝了操作"))
        except ValueError:
            message = "车端返回了无效响应"
        raise _error(409 if exc.response.status_code < 500 else 502, message) from exc
    except (httpx.HTTPError, RuntimeError, ValueError) as exc:
        raise _error(502, f"未能确认车端执行状态，请刷新核对：{exc}") from exc


async def dispatch_saved(db, item, request):
    db.refresh(item)
    current = execution(item)
    if current and (current.get('sync_state') == 'cancel_pending' or current['state'] in {'completed','cancelled','failed'}):
        return current
    if current and current.get('request_fingerprint') and hashlib.sha256(json.dumps(request,sort_keys=True,allow_nan=False).encode()).hexdigest() != current['request_fingerprint']:
        raise _error(409, '原请求校验失败，禁止派发；请核对或取消旧请求')
    try:
        result = await _call(db, 'task', request)
        if (not isinstance(result,dict) or result.get('run_id') != request['run_id']
                or result.get('task_id') != item.id or result.get('kind',request['kind']) != request['kind']
                or result.get('state') not in STATES):
            store_execution(db,item,{**execution(item),'sync_state':'record_mismatch','poll_required':False,
                                     'message':'车端创建回执不匹配，禁止重试派发；请核对并取消旧请求'})
            db.commit()
            return execution(item)
        return result
    except HTTPException as exc:
        value = execution(item)
        if value.get('sync_state') == 'cancel_pending' or value['state'] in {'completed','cancelled','failed'}:
            return value
        message = exc.detail.get('message',str(exc.detail)) if isinstance(exc.detail,dict) else str(exc.detail)
        value = {**value, 'sync_state':'unreachable' if exc.status_code>=500 else 'dispatch_rejected',
                 'message':message,'poll_required':exc.status_code>=500}
        store_execution(db,item,value);db.commit()
        return execution(item)


@router.post("")
async def create_execution(payload: dict = Body(...), db: Session = Depends(get_db),
                           user: User = Depends(require_permission("robots.read"))):
    kind = payload.get("kind")
    if kind not in {"delivery", "patrol"}:
        raise _error(422, "任务类型无效")
    _permission(user, kind)
    run_id = payload.get("run_id")
    if not isinstance(run_id, str) or not 1 <= len(run_id) <= 128:
        raise _error(422, "任务请求标识无效")
    task_id = payload.get("task_id") or str(uuid5(NAMESPACE_URL, f"navigation:{kind}:{run_id}"))
    model = MissionTask if kind == "delivery" else PatrolTask
    item = db.get(model, task_id)
    if item is None:
        if payload.get("task_id"):
            raise _error(404, "原业务任务不存在")
        robot = db.get(Robot, payload.get("robot_id")) if payload.get("robot_id") else None
        if not robot:
            raise _error(422, "请选择业务数据库中的小车")
        map_id = payload.get("map_id")
        if map_id and db.get(MapModel, map_id) is None:
            raise _error(422, "业务地图不存在")
        item = model(id=task_id, name=str(payload.get("name") or ("文件运输" if kind == "delivery" else "多点巡航"))[:128],
                     robot_id=robot.id, map_id=map_id, created_by=user.id)
        if kind == "delivery":
            item.cargo = item.cargo_name = str(payload.get("cargo") or "文件")[:255]
            item.origin = item.start_location = str(payload.get("pickup_name") or "当前装件点")[:255]
            points = payload.get("waypoints")
            if isinstance(points, list) and points and isinstance(points[0], dict):
                item.destination = item.end_location = str(points[0].get("name") or "自选位置")[:255]
        db.add(item)
        db.flush()
    previous = execution(item)
    if not item.robot_id:
        raise _error(422, "此任务尚未分配小车，请先修改任务")
    _check_binding(db, item.robot_id)
    if payload.get("robot_id") not in (None, item.robot_id):
        raise _error(409, "请求车辆与任务车辆不一致")
    if previous and previous["run_id"] != run_id:
        raise _error(409, "该业务任务已绑定执行记录，请新建任务")
    wire_payload = {**payload, "task_id": task_id}
    try:
        fingerprint = hashlib.sha256(json.dumps(wire_payload, sort_keys=True, allow_nan=False).encode()).hexdigest()
    except (ValueError, TypeError) as exc:
        raise _error(422, "执行请求包含无效参数") from exc
    if previous and previous.get("request_fingerprint") not in {None, fingerprint}:
        raise _error(409, "请求内容与已保存原请求不同；请重试原请求，或确认取消旧任务后重新创建")
    if previous and (previous['state'] in {'completed','cancelled','failed'} or previous.get('sync_state') in {'cancel_pending','record_mismatch','query_rejected'}):
        return previous
    if not previous:
        if item.status not in {"queued", "pending"}:
            raise _error(409, "此业务任务当前不能派发")
        store_execution(db, item, {"run_id": run_id, "task_id": task_id, "kind": kind, "state": "unconfirmed",
                               "message": "执行请求已保存，等待车端确认", "request": wire_payload, "request_fingerprint": fingerprint})
        record_audit(db, user, "navigation.prepare", "task", task_id)
        db.commit()
        diagnostic_emit('task.changed', 'dispatch_prepared', module='navigation_tasks',
                        robot_id=item.robot_id, task_id=task_id, run_id=run_id)
    result = await dispatch_saved(db, item, wire_payload)
    if result.get("run_id") != run_id or result.get("task_id") != task_id:
        raise _error(502, "车端任务标识不一致，尚未确认派发")
    store_execution(db, item, result)
    db.commit()
    await control_lease_manager.observe_run(execution(item))
    return execution(item)


@router.get("/{kind}/{task_id}")
async def get_execution(kind: str, task_id: str, db: Session = Depends(get_db),
                        user: User = Depends(require_permission("robots.read"))):
    _permission(user, kind, False)
    item = _task(db, kind, task_id)
    previous = execution(item)
    if not previous:
        return {"state": "idle", "message": "此任务尚未配置地图目标"}
    _check_binding(db, item.robot_id)
    binding = vehicle_binding(db)
    result = await refresh_execution(db, item, _gateway(db), binding_guard=lambda:vehicle_binding(db)==binding)
    await control_lease_manager.observe_run(result)
    return result



async def _prepare_task_start(db, item, previous, user, guard):
    manager = control_lease_manager
    binding = vehicle_binding(db)
    gateway = get_robot_gateway(binding[1])
    generation = manager.generation

    def check():
        if guard:
            guard()
        db.refresh(item)
        live = execution(item)
        if (vehicle_binding(db) != binding or not live or live.get("sync_state") == "cancel_pending"
                or any(live.get(key) != previous.get(key) for key in ("run_id", "state", "version"))):
            raise _error(409, "待启动任务或车辆绑定已变化")

    async def park():
        lease_state = await gateway.control_lease()
        check()
        if (manager.generation != generation or not lease_state.get("fresh")
                or lease_state.get("emergency_stop") is not False
                or lease_state.get("mode") not in {"stop", "auto", "manual"}):
            raise _error(409, "控制状态未确认、车端需要更新或当前禁止导航")
        held = manager.current
        if held is not None and (held.user_id != user.id or (held.robot_id, held.address) != binding
                                or held.purpose not in {"manual", "auto"}):
            raise _error(409, "控制权已被其他操作占用")
        if lease_state.get("owner") is not None and (held is None or
                any(lease_state.get(key) != value for key, value in held.identity().items())):
            raise _error(409, "控制权已被其他操作占用")
        await manager.stop()
        if manager.generation != generation + 1:
            raise _error(409, "控制代次已变化")
        if held is not None:
            lease_state = await gateway.control_lease()
            if (not lease_state.get("fresh") or lease_state.get("owner") is not None
                    or lease_state.get("controller_id") != held.controller_id):
                raise _error(409, "旧租约尚未确认释放")
        if manager.generation != generation + 1 or vehicle_binding(db) != binding:
            raise _error(409, "车辆绑定或控制代次已变化")
        return await gateway.navigation_request("task/park", {
            **{key: lease_state.get(key) for key in ("controller_id", "control_epoch", "owner")},
            **{key: previous.get(key) for key in ("run_id", "task_id", "kind", "version", "state")},
        })

    async with navigation_parking(manager, park, lambda: vehicle_binding(db) == binding) as (parked_generation, result):
        if guard:
            guard(parked_generation=parked_generation)
        check()
        parked = result.get("lease")
        if not isinstance(parked, dict) or not all(parked.get(key) for key in ("controller_id", "control_epoch")):
            raise _error(409, "停车回执缺少控制器代次")
        return binding, parked, check


async def apply_execution_action(kind, task_id, payload, db, user, *, guard=None):
    _permission(user, kind)
    item = _task(db, kind, task_id)
    _check_binding(db, item.robot_id)
    previous = execution(item)
    if not previous or payload.get("run_id") != previous["run_id"]:
        raise _error(409, "执行任务已变化，请刷新")
    if guard:
        guard()
    action = payload.get("action")
    if action == 'retry':
        if previous['state'] != 'unconfirmed' or not previous.get('request') or previous.get('sync_state') in {'cancel_pending','record_mismatch'}:
            raise _error(409, '当前状态不能重试派发，请核对并取消旧请求')
        binding = vehicle_binding(db)
        checked = await refresh_execution(db,item,_gateway(db),force=True,binding_guard=lambda:vehicle_binding(db)==binding)
        if checked['state'] != 'unconfirmed' or checked.get('sync_state') != 'record_missing':
            return checked
        result = await dispatch_saved(db,item,checked['request'])
    else:
        if action == 'cancel' and previous['state'] not in {'completed','cancelled','failed'}:
            store_execution(db,item,{**previous,'sync_state':'cancel_pending','poll_required':False,
                                     'message':'正在取消旧请求；车端确认前不能更换目标'})
            db.commit()
        wire = {"run_id": previous["run_id"], "task_id": task_id, "kind": kind, "action": action}
        if action != 'cancel' and previous.get('sync_state') in {'cancel_pending','record_missing','record_mismatch','query_rejected','unreachable'}:
            raise _error(409, '车端执行状态未核实，请先核对或取消旧请求')
        lease = None
        motion_phases = {"loaded": "waiting_load", "start": "prepared", "resume": "paused"}
        if action in motion_phases and previous["state"] != motion_phases[action]:
            raise _error(409, "当前任务阶段不允许此操作，请刷新后核对")
        if action in motion_phases or (action == "handover" and previous.get("return_to_start") is True):
            permission = "missions.manage" if kind == "delivery" else "patrol.manage"
            try:
                binding, parked, check = await _prepare_task_start(db, item, previous, user, guard)
                lease = await control_lease_manager.acquire_for_run(
                    binding, user.id, permission, wire["run_id"], parked=parked)
                wire["expected_version"] = previous.get("version")
            except (httpx.HTTPError, RuntimeError, ValueError) as exc:
                raise _error(409, "未取得实车控制租约，请核对停车与连接状态") from exc
            wire["control_lease"] = lease.identity()
        try:
            if guard:
                guard()
            if lease is not None:
                check()
                if control_lease_manager.current is not lease:
                    raise _error(409, "控制租约已变化")
            gateway = get_robot_gateway(lease.address) if lease is not None else None
            result = await _call(db, "task/action", wire, gateway=gateway)
            if result.get("task_id") != task_id or result.get("run_id") != wire["run_id"]:
                raise _error(502, "车端执行记录不匹配")
        except (Exception, asyncio.CancelledError):
            if lease is not None:
                await control_lease_manager.release_run(wire["run_id"], lease=lease)
            raise
    if result.get("task_id") != task_id or result.get("run_id") != previous["run_id"]:
        raise _error(502, "车端执行记录不匹配")
    store_execution(db, item, result)
    record_audit(db, user, "navigation." + str(payload.get("action")), "task", task_id, after=result)
    db.commit()
    await control_lease_manager.observe_run(execution(item))
    return execution(item)


@router.post("/{kind}/{task_id}/action")
async def execution_action(kind: str, task_id: str, payload: dict = Body(...), db: Session = Depends(get_db),
                           user: User = Depends(require_permission("robots.read"))):
    return await apply_execution_action(kind, task_id, payload, db, user)
