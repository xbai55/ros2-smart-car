from uuid import uuid4
from sqlalchemy import select
from app.models import User,Notification


def test_bulk_read_is_scoped_idempotent_and_keeps_later_notifications(client,login,seeded_db):
    db=seeded_db
    operator=db.scalar(select(User).where(User.username=='operator'))
    auditor=db.scalar(select(User).where(User.username=='auditor'))
    own,other=str(uuid4()),str(uuid4())
    db.add_all([Notification(id=own,user_id=operator.id,kind='incident',title='own'),Notification(id=other,user_id=auditor.id,kind='incident',title='other')]);db.commit()
    h={'Authorization':'Bearer '+login('operator','operator123')}
    r=client.post('/api/v1/notifications/read-all',json={},headers=h);assert r.status_code==200,r.text
    assert own in r.json()['read_ids'] and other not in r.json()['read_ids']
    db.expire_all();assert db.get(Notification,own).read and not db.get(Notification,other).read
    assert client.post('/api/v1/notifications/read-all',json={},headers=h).json()['updated_count']==0
    later=str(uuid4());db.add(Notification(id=later,user_id=operator.id,kind='incident',title='new'));db.commit()
    assert not db.get(Notification,later).read
    assert client.post('/api/v1/notifications/read-all',json={}).status_code==401
