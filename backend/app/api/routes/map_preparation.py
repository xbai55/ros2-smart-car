import json
import time
from uuid import uuid5,NAMESPACE_URL
from fastapi import APIRouter,Depends,HTTPException
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from ...models import MapPreparation,User
from ...schemas.ops import SlamMapIn
from ...services.control_access import require_bound_vehicle
from ...services.map_preparation import serialize,cleanup
from ...services.ops import record_audit
from ...services.control_leases import control_lease_manager
from ..deps import get_db,require_permission

router=APIRouter(prefix='/maps/slam',tags=['maps'])


class PreparationIn(SlamMapIn):
    session_id: str


@router.post('/finish-for-tasks',status_code=202)
def create_preparation(payload:PreparationIn,db:Session=Depends(get_db),user:User=Depends(require_permission('maps.manage'))):
    if 'robots.control' not in user.permissions: raise HTTPException(403,'缺少车辆控制权限')
    if not 1<=len(payload.session_id)<=128: raise HTTPException(422,'建图会话无效')
    robot,address=require_bound_vehicle(db,payload.robot_id)
    ident=str(uuid5(NAMESPACE_URL,f'map-preparation:{robot}:{user.id}:{payload.request_id}'))
    existing=db.get(MapPreparation,ident)
    if existing:
        if json.loads(existing.request)!=payload.model_dump(mode='json'): raise HTTPException(409,'请求标识已用于不同参数')
        return serialize(existing)
    lease=control_lease_manager.current
    if not lease or lease.purpose!='mapping' or lease.user_id!=user.id or (lease.robot_id,lease.address)!=(robot,address):
        raise HTTPException(409,'请在当前账户的本轮建图中结束并准备任务')
    if db.scalar(select(MapPreparation.id).where(MapPreparation.active_robot==robot)):
        raise HTTPException(409,'该小车已有地图准备操作')
    item=MapPreparation(id=ident,user_id=user.id,robot_id=robot,active_robot=robot,address=address,
                        session_id=payload.session_id,lease_run_id=lease.run_id,request=payload.model_dump_json(),created_at=time.time())
    db.add(item)
    record_audit(db,user,'maps.prepare_tasks','robot',robot,after={'operation_id':ident,'session_id':payload.session_id})
    try: db.commit()
    except IntegrityError:
        db.rollback()
        winner=db.get(MapPreparation,ident)
        if winner: return serialize(winner)
        raise HTTPException(409,'该小车已有地图准备操作')
    return serialize(item)


def owned(db,ident,user):
    job=db.get(MapPreparation,ident)
    if job is None or job.user_id!=user.id: raise HTTPException(404,'地图准备操作不存在')
    return job


@router.get('/preparations/{ident}')
def get_preparation(ident:str,db:Session=Depends(get_db),user:User=Depends(require_permission('maps.read'))):
    return serialize(owned(db,ident,user))


@router.post('/preparations/{ident}/cancel')
async def cancel_preparation(ident:str,db:Session=Depends(get_db),user:User=Depends(require_permission('robots.control'))):
    job=owned(db,ident,user)
    if job.state not in {'pending','running'}: return serialize(job)
    job.state,job.phase,job.message='cancelled','cancelled','地图准备已取消，已保存地图仍保留'
    job.active_robot=None;job.finished_at=time.time()
    db.commit()
    try: await cleanup(job)
    except Exception: pass
    return serialize(job)


@router.post('/preparations/{ident}/retry',status_code=202)
async def retry_preparation(ident:str,db:Session=Depends(get_db),user:User=Depends(require_permission('maps.manage'))):
    if 'robots.control' not in user.permissions:raise HTTPException(403,'缺少车辆控制权限')
    job=owned(db,ident,user)
    if job.state in {'pending','running'}:return serialize(job)
    if job.state!='failed' or job.phase!='retry_available' or not job.map_id:
        raise HTTPException(409,'当前交接不可重试，请使用已保存地图手动定位')
    if require_bound_vehicle(db,job.robot_id)!=(job.robot_id,job.address) or control_lease_manager.current is not None:
        raise HTTPException(409,'控制权或车辆绑定已变化，请先停车并释放控制权')
    from ...gateway import get_robot_gateway
    gateway=get_robot_gateway(job.address)
    try:info=await gateway.navigation_request('handoff-diagnostic',{'request_id':job.id})
    except Exception:raise HTTPException(503,'暂时无法核对车端交接记录，请恢复连接后重试') from None
    if not info.get('valid') or info.get('used'):raise HTTPException(409,'自动位姿已过期、失效或使用，请手动定位')
    if db.scalar(select(MapPreparation.id).where(MapPreparation.active_robot==job.robot_id)):
        raise HTTPException(409,'该小车已有地图准备操作')
    job.state,job.phase,job.message='pending','pending','正在原地重试自动定位'
    job.active_robot=job.robot_id;job.finished_at=None
    try:db.commit()
    except IntegrityError:
        db.rollback();raise HTTPException(409,'该小车已有地图准备操作') from None
    return serialize(job)
