import math,json,time
from uuid import uuid4
import pytest
from pydantic import ValidationError
from sqlalchemy import select
from app.models import Incident,FallReview,Notification,Robot
from app.services.fall_review import ReviewDecision,SmokeDecision,finish_review,alert_clause
from app.services.safety_alert_settings import AlertThresholds,read_thresholds,save_thresholds

@pytest.mark.parametrize('score',[-.1,1.1,float('nan'),float('inf'),'0.9',True,None])
def test_bad_scores_are_rejected(score):
    for cls,extra in [(SmokeDecision,{}),(ReviewDecision,{'person':'present','posture':'fallen_or_lying'})]:
        with pytest.raises(ValidationError):cls(verdict='supported',score=score,reason='观察依据',**extra)

@pytest.mark.parametrize('category',['smoke_fire','fallen_person'])
@pytest.mark.parametrize('verdict,score,expected',[('supported',.79,'suppressed'),('supported',.8,'supported'),('uncertain',.99,'uncertain'),('rejected',.9,'rejected'),('failed',None,'failed')])
def test_only_supported_at_threshold_notifies(seeded_db,monkeypatch,category,verdict,score,expected):
    from app.services import fall_review
    db=seeded_db;calls=[];monkeypatch.setattr(fall_review,'notify_incident',lambda *args:calls.append(True))
    save_thresholds(db,AlertThresholds());ident=str(uuid4())
    item=Incident(id=ident,type=category,severity='warning',title='candidate',description='',location='',evidence='{}')
    db.add(item);db.flush();job=FallReview(incident_id=ident,raw_key='',state='running',started_at=time.time());db.add(job);db.flush()
    finish_review(db,job,verdict,{'score':score,'reason':'遮挡或可见证据'} if score is not None else None)
    db.flush();assert job.state==expected;assert bool(calls)==(expected=='supported')
    visible=db.scalar(select(Incident.id).where(Incident.id==ident,alert_clause()))
    assert bool(visible)==(expected=='supported')
    db.rollback()

def test_thresholds_persist_and_validate_permissions(client,login,seeded_db):
    h={'Authorization':'Bearer '+login('operator','operator123')}
    value={'smoke_fire':{'candidate':.65,'review':.85},'fallen_person':{'candidate':.55,'review':.9}}
    r=client.put('/api/v1/incidents/safety/thresholds',json=value,headers=h);assert r.status_code==200,r.text
    assert client.get('/api/v1/incidents/safety/thresholds',headers=h).json()==value
    value['smoke_fire']['review']=1.1
    assert client.put('/api/v1/incidents/safety/thresholds',json=value,headers=h).status_code==422
    h={'Authorization':'Bearer '+login('auditor','auditor123')}
    assert client.put('/api/v1/incidents/safety/thresholds',json=AlertThresholds().model_dump(),headers=h).status_code==403
    save_thresholds(seeded_db,AlertThresholds());seeded_db.commit()


def test_review_prompts_and_structured_scores():
    import asyncio
    from types import SimpleNamespace
    from app.services.fall_review import review_image
    captured=[]
    async def complete(messages,tools):
        captured.append(messages)
        return {'content':json.dumps({'verdict':'uncertain','score':.25,'reason':'椅脚遮挡，不能确认独立人体',
            **({'person':'uncertain','posture':'unknown'} if len(captured)==1 else {})})}
    provider=SimpleNamespace(complete=complete)
    for category in ['fallen_person','smoke_fire']:
        r=asyncio.run(review_image(provider,b'jpeg',{'box':[0,0,10,10]},category))
        assert r['verdict']=='uncertain' and r['score']==.25
    assert '多个人的腿脚' in captured[0][0]['content']
    assert '反光' in captured[1][0]['content']
    assert captured[0][1]['content'][1]['image_url']['url'].startswith('data:image/jpeg;base64,')


@pytest.mark.parametrize('category',['smoke_fire','fallen_person'])
@pytest.mark.parametrize('score',[.49,None,float('nan'),True])
def test_candidate_score_gate_does_not_create_incident_or_notice(seeded_db,tmp_path,category,score):
    from test_safety_ingest import event
    from app.services.safety_ingest import ingest_event
    from app.services.storage import LocalStorageService
    db=seeded_db;save_thresholds(db,AlertThresholds())
    candidate=event();candidate['type']=category;candidate['evidence']['confidence']=score
    before=len(db.scalars(select(Incident)).all())
    assert ingest_event(db,db.scalar(select(Robot)),candidate,LocalStorageService(str(tmp_path))) is None
    assert len(db.scalars(select(Incident)).all())==before
    db.rollback()
