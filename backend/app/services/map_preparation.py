from .service_budgets import ACTION_WAIT, POSE_WAIT, HANDOFF_TOTAL
"""Durable orchestration; volatile pose authority remains on the vehicle."""
import asyncio
import json
import time

from sqlalchemy import select, update
from ..db.session import SessionLocal
from ..models import AppSetting, MapPreparation, User
from ..gateway import get_robot_gateway
from .control_access import require_bound_vehicle
from .control_leases import control_lease_manager


def serialize(job):
    result={k:getattr(job,k) for k in ['id','state','phase','message','map_id','created_at','started_at','finished_at']}
    result.update(elapsed_sec=max(0.,(job.finished_at or time.time())-(job.started_at or job.created_at)),budget_sec=HANDOFF_TOTAL)
    return result


def recover_map_preparations():
    with SessionLocal() as db:
        db.execute(update(MapPreparation).where(MapPreparation.state.in_(['pending','running'])).values(
            state='failed',phase='interrupted',message='应用重启，未自动重放地图准备；请重新操作或手动定位',
            active_robot=None,finished_at=time.time()))
        db.commit()


def active_job(db, ident):
    job=db.get(MapPreparation,ident)
    if job is None or job.state not in {'pending','running'}:
        raise RuntimeError('地图准备已取消或结束')
    user=db.get(User,job.user_id)
    if not user or not user.active or not {'maps.manage','robots.control'}<=user.permissions:
        raise RuntimeError('地图准备权限已变化')
    if require_bound_vehicle(db,job.robot_id)!=(job.robot_id,job.address):
        raise RuntimeError('绑定的小车已变化')
    return job


def phase(ident, name, message):
    with SessionLocal() as db:
        job=active_job(db,ident)
        job.phase,job.message=name,message
        db.commit()


def register_map(ident, exported):
    from ..api.routes.maps import register_slam_export
    from ..schemas.ops import SlamMapIn
    with SessionLocal() as db:
        job=active_job(db,ident)
        payload=SlamMapIn.model_validate_json(job.request)
        item=register_slam_export(db,payload,db.get(User,job.user_id),exported)
        job=db.get(MapPreparation,ident)
        job.map_id=item['id']
        db.commit()
        return item['id']


class HandoffWaitTimeout(RuntimeError):
    pass

async def handoff_request(gateway, path, payload, *, deadline=None):
    """Retry transport/readiness only. Never repeat a publication with unknown outcome."""
    import httpx
    deadline=deadline if deadline is not None else time.monotonic()+ACTION_WAIT
    while True:
        remaining=deadline-time.monotonic()
        if remaining<=0:raise HandoffWaitTimeout('等待预算已用尽，地图已保留，请核对交接状态')
        try:return await asyncio.wait_for(gateway.navigation_request(path,payload),remaining)
        except (TimeoutError,httpx.TransportError,httpx.HTTPStatusError) as exc:
            retryable=isinstance(exc,(TimeoutError,httpx.TransportError))
            if isinstance(exc,httpx.HTTPStatusError):
                try:detail=exc.response.json().get('detail',{})
                except ValueError:detail={}
                retryable=exc.response.status_code==503 and isinstance(detail,dict) and detail.get('retryable') is True
            if not retryable:raise
            if path in {'handoff-load','handoff-seed'}:
                info=await handoff_request(gateway,'handoff-diagnostic',{'handoff_id':payload['handoff_id']},deadline=deadline)
                if not info.get('valid'):raise RuntimeError('自动交接记录已失效，请手动定位') from exc
                if path=='handoff-load' and info.get('loaded'):
                    return await handoff_request(gateway,'handoff-status',{'handoff_id':payload['handoff_id']},deadline=deadline)
                if path=='handoff-load' and info.get('loading'):
                    # May still be executing; query until the result is known.
                    if time.monotonic()>=deadline:raise HandoffWaitTimeout('正在等待地图加载回执，地图已保留') from exc
                    await asyncio.sleep(.3);continue
                if path=='handoff-seed' and info.get('used'):
                    if info.get('seed_outcome')=='published':
                        return await handoff_request(gateway,'handoff-status',{'handoff_id':payload['handoff_id']},deadline=deadline)
                    raise RuntimeError('初始位姿发送结果不明，未重复发送，请手动定位') from exc
            if time.monotonic()>=deadline:raise HandoffWaitTimeout('定位接口暂未就绪，地图已保留，可重试自动定位') from exc
            await asyncio.sleep(.3)

async def prepare(ident):
    overall_deadline=time.monotonic()+HANDOFF_TOTAL
    with SessionLocal() as db:
        job=active_job(db,ident)
        address,session_id,user_id,run_id=job.address,job.session_id,job.user_id,job.lease_run_id
        map_id=job.map_id
    gateway=get_robot_gateway(address)
    if map_id:
        # Explicit retry reuses vehicle-held authority, never a persisted pose.
        info=await handoff_request(gateway,'handoff-diagnostic',{'request_id':ident})
        if not info.get('valid') or info.get('used'):
            raise RuntimeError('自动位姿记录已失效或已使用，请手动定位')
        exported={'handoff_id':info['handoff_id'],'digest':info['digest']}
    else:
        lease=control_lease_manager.current
        if not lease or lease.purpose!='mapping' or lease.user_id!=user_id or lease.address!=address or lease.run_id!=run_id:
            raise RuntimeError('本轮建图控制权已失效，请重新建图或手动定位')
        phase(ident,'stopping','正在停车并保存本轮地图与当前位置')
        exported=await gateway.finish_mapping_for_tasks({'request_id':ident,'session_id':session_id,'control_lease':lease.identity()})
        phase(ident,'saving','正在登记地图，位姿已由车端捕获')
        if control_lease_manager.current is not lease:raise RuntimeError('地图交接期间控制权已变化')
        await control_lease_manager.release_run(lease.run_id,lease=lease)
        stopped=await gateway.stop()
        if stopped.get('controller_confirmed') is not True or stopped.get('stationary_confirmed') is not True:
            raise RuntimeError('未确认车辆停车，未启动导航')
        map_id=await asyncio.to_thread(register_map,ident,exported)
    wire={'handoff_id':exported['handoff_id']}
    phase(ident,'loading','正在加载刚保存的地图并启动定位')
    await handoff_request(gateway,'handoff-load',{**wire,'map_id':map_id,'digest':exported['digest']},deadline=min(overall_deadline,time.monotonic()+POSE_WAIT))
    phase(ident,'waiting_pose','正在等待地图和初始定位接口就绪')
    deadline=min(overall_deadline,time.monotonic()+POSE_WAIT)
    while time.monotonic()<deadline:
        phase(ident,'waiting_pose','正在等待地图和初始定位接口就绪')
        value=await handoff_request(gateway,'handoff-status',wire,deadline=deadline)
        if value.get('state')=='failed': raise RuntimeError(value['message'])
        if value.get('initial_pose_ready'): break
        await asyncio.sleep(.3)
    else: raise HandoffWaitTimeout('定位接口启动超时，地图已保留，可重试自动定位')
    phase(ident,'localizing','正在自动复用当前位置，等待定位检查')
    # Send once. A transport failure has unknown outcome and must not be retried.
    await handoff_request(gateway,'handoff-seed',wire)
    deadline=min(overall_deadline,time.monotonic()+POSE_WAIT)
    while time.monotonic()<deadline:
        phase(ident,'localizing','当前位置已自动发送，等待定位收敛与静止稳定性检查')
        value=await handoff_request(gateway,'handoff-status',wire,deadline=deadline)
        if value.get('state')=='failed': raise RuntimeError(value['message'])
        if value.get('localized') is True and value.get('state')=='ready':
            with SessionLocal() as db:
                job=active_job(db,ident)
                choice=db.scalar(select(AppSetting).where(AppSetting.key=='navigation_map_id'))
                if choice is None:
                    from uuid import uuid4
                    db.add(AppSetting(id=str(uuid4()),key='navigation_map_id',value=map_id))
                else: choice.value=map_id
                job.state,job.phase='completed','ready'
                job.message='地图与定位已就绪，当前位置已自动复用；任务仍需通过权限与能力检查'
                job.active_robot=None;job.finished_at=time.time()
                db.commit()
            return
        await asyncio.sleep(.5)
    raise RuntimeError('自动定位未通过检查，地图已保留，请核对现场并手动定位')


async def cleanup(job):
    gateway=get_robot_gateway(job.address)
    owned=False
    try:
        result=await asyncio.wait_for(gateway.navigation_request('handoff-cancel',{'request_id':job.id}),8)
        owned=result.get('cancelled') is True
    finally:
        lease=control_lease_manager.current
        if lease and lease.run_id==job.lease_run_id and lease.address==job.address:
            owned=True
            await control_lease_manager.release_run(lease.run_id,lease=lease)
        if owned: await asyncio.wait_for(gateway.stop(),5)


async def run_map_preparations():
    while True:
        with SessionLocal() as db:
            ident=db.scalar(select(MapPreparation.id).where(MapPreparation.state=='pending').order_by(MapPreparation.created_at).limit(1))
            if ident:
                claimed=db.execute(update(MapPreparation).where(MapPreparation.id==ident,MapPreparation.state=='pending')
                    .values(state='running',started_at=time.time()))
                db.commit()
                if claimed.rowcount!=1: ident=None
        if not ident:
            await asyncio.sleep(.3)
            continue
        error=None
        retry_available=False
        try:
            await asyncio.wait_for(prepare(ident),HANDOFF_TOTAL)
        except asyncio.CancelledError:
            error='应用退出，准备已停止；地图保留，请手动定位'
            raise
        except Exception as exc:
            import httpx
            retry_available=False
            if isinstance(exc,HandoffWaitTimeout):
                try:
                    with SessionLocal() as db:address=db.get(MapPreparation,ident).address
                    info=await asyncio.wait_for(get_robot_gateway(address).navigation_request('handoff-diagnostic',{'request_id':ident}),3)
                    retry_available=info.get('valid') is True and info.get('used') is False
                except Exception:pass
            if isinstance(exc,httpx.HTTPStatusError):
                try:
                    detail=exc.response.json().get('detail','车端未确认地图准备')
                    error=str(detail.get('message',detail) if isinstance(detail,dict) else detail)[:450]
                except ValueError: error='车端未确认地图准备'
            else: error=str(exc)[:450] or '地图准备超时，请手动定位'
        finally:
            if error:
                with SessionLocal() as db:
                    job=db.get(MapPreparation,ident)
                    if job.state in {'pending','running'}:
                        job.state,job.phase,job.message='failed','retry_available' if retry_available else 'manual_required',error
                        job.active_robot=None;job.finished_at=time.time();db.commit()
                    address=job.address
                if not retry_available:
                    try: await cleanup(job)
                    except Exception: pass
