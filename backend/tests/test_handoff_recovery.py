import asyncio
import httpx
import pytest
from types import SimpleNamespace as N
from app.services.map_preparation import handoff_request

@pytest.mark.parametrize('outcome',['published','unknown'])
def test_ambiguous_seed_is_queried_and_never_repeated(outcome):
    calls=[]
    async def request(path,payload):
        calls.append(path)
        if path=='handoff-seed':raise httpx.ReadTimeout('timeout')
        if path=='handoff-diagnostic':return {'valid':True,'used':True,'seed_outcome':outcome}
        return {'state':'localizing'}
    operation=handoff_request(N(navigation_request=request),'handoff-seed',{'handoff_id':'h'})
    if outcome=='unknown':
        with pytest.raises(RuntimeError,match='结果不明'):asyncio.run(operation)
    else:assert asyncio.run(operation)['state']=='localizing'
    assert calls.count('handoff-seed')==1


def test_lost_load_ack_reuses_existing_load():
    calls=[]
    async def request(path,payload):
        calls.append(path)
        if path=='handoff-load':raise httpx.ReadTimeout('lost acknowledgement')
        if path=='handoff-diagnostic':return {'valid':True,'loaded':True}
        return {'state':'starting'}
    assert asyncio.run(handoff_request(N(navigation_request=request),'handoff-load',{'handoff_id':'h'}))['state']=='starting'
    assert calls.count('handoff-load')==1


def test_only_explicit_readiness_errors_are_retried():
    calls=[]
    async def request(path,payload):
        calls.append(path)
        if len(calls)==1:
            response=httpx.Response(503,json={'detail':{'retryable':True}},request=httpx.Request('POST','http://vehicle'))
            raise httpx.HTTPStatusError('wait',request=response.request,response=response)
        return {'state':'ready'}
    assert asyncio.run(handoff_request(N(navigation_request=request),'handoff-status',{'handoff_id':'h'}))['state']=='ready'
    assert len(calls)==2



def test_exhausted_shared_budget_does_not_issue_another_request():
    import time
    from app.services.map_preparation import HandoffWaitTimeout
    calls=[]
    async def request(path,payload):calls.append(path);return {}
    with pytest.raises(HandoffWaitTimeout):
        asyncio.run(handoff_request(N(navigation_request=request),'handoff-status',{},deadline=time.monotonic()-1))
    assert calls==[]
