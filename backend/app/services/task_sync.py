"""Read-only execution reconciliation; missing records never imply cancellation."""
import time
import httpx
from fastapi import HTTPException
from .navigation_execution import execution, store_execution

TERMINAL = {'completed','cancelled','failed'}
STATES = TERMINAL | {'prepared','waiting_load','planning','running','returning','dwelling','paused','waiting_handover'}

def classify(exc):
    if isinstance(exc,httpx.HTTPStatusError):
        try:detail=exc.response.json().get('detail')
        except ValueError:detail=None
        if (exc.response.status_code==404 and isinstance(detail,dict) and detail.get('code')=='NAVIGATION_RUN_NOT_FOUND') or (exc.response.status_code==422 and detail=='车端没有此任务的执行记录'):
            return 'record_missing','车端无此执行记录；可核对并重试原请求，或取消旧请求后新建任务'
        return 'query_rejected','车端拒绝状态查询，请核对协议或任务记录'
    return 'unreachable','无法连接车端，尚不能确认任务是否执行或取消'

async def refresh_execution(db,item,gateway,*,force=False,binding_guard=None):
    previous=execution(item)
    if not previous or previous['state'] in TERMINAL:return previous
    if not force and (previous.get('poll_required') is False or time.time()<previous.get('next_poll_at',0)):
        return previous
    try:
        value=await gateway.navigation_request('task',query={'run_id':previous['run_id']})
        if binding_guard is not None and not binding_guard():
            raise HTTPException(409, '实车绑定已变化，已丢弃旧查询结果')
        if not isinstance(value,dict) or value.get('run_id')!=previous['run_id'] or value.get('task_id')!=item.id or value.get('kind',previous.get('kind'))!=previous.get('kind') or value.get('state') not in STATES:
            sync,message='record_mismatch','车端执行记录不匹配；禁止重试派发，请核对并取消旧请求'
        else:
            value={**value,'sync_state':'confirmed','poll_required':value['state'] not in TERMINAL,'sync_failures':0,'next_poll_at':0}
            store_execution(db,item,value);db.commit();return execution(item)
    except httpx.HTTPError as exc:
        sync,message=classify(exc)
    except (ValueError,RuntimeError):
        sync,message="query_rejected","车端状态响应无效或接口配置不可用，请核对后恢复"
    if binding_guard is not None and not binding_guard():
        raise HTTPException(409, '实车绑定已变化，已丢弃旧查询结果')
    # Never guess a vehicle version or raise it above a delayed real reply.
    failures=previous.get('sync_failures',0)+1
    value={**previous,'sync_state':sync,'message':message,'sync_failures':failures,
           'poll_required':sync=='unreachable','next_poll_at':time.time()+min(30,2**min(failures,5))}
    store_execution(db,item,value);db.commit();return execution(item)
