import base64
from datetime import datetime, timezone, timedelta
from io import BytesIO
from uuid import uuid4

from PIL import Image
import pytest
from sqlalchemy import select

from app.models import Incident, Notification, Robot
from app.services.safety_ingest import ingest_event
from app.services.storage import LocalStorageService


def test_notification_websocket_rejects_anonymous(client):
    from starlette.websockets import WebSocketDisconnect
    with pytest.raises(WebSocketDisconnect) as rejected:
        with client.websocket_connect('/ws/v1/notifications'):
            pass
    assert rejected.value.code == 1008


def test_notification_cursor_keeps_all_same_timestamp_messages(client, seeded_db, monkeypatch):
    from sqlalchemy.orm import sessionmaker
    from app.api.routes import ws
    from app.models import User, Role
    from app.core.security import create_access_token
    from app.core.config import settings
    db = seeded_db
    user = User(id=str(uuid4()), username='ws-test-' + str(uuid4()), password_hash='unused', active=True)
    user.roles = [db.scalar(select(Role).where(Role.name == 'admin'))]
    db.add(user)
    stamp = datetime(2026, 10, 17, tzinfo=timezone.utc)
    expected = set()
    for index in range(25):
        ident = str(uuid4())
        expected.add(ident)
        db.add(Notification(id=ident, user_id=user.id, kind='incident', title=str(index), created_at=stamp))
    db.commit()
    monkeypatch.setattr(ws, 'SessionLocal', sessionmaker(bind=db.get_bind(), expire_on_commit=False))
    token = create_access_token(user.id, settings.jwt_secret, expires_delta=timedelta(minutes=5))
    with client.websocket_connect('/ws/v1/notifications?token=' + token) as socket:
        seen = {socket.receive_json()['notification']['id'] for _ in range(25)}
    assert seen == expected


def event():
    output = BytesIO()
    Image.new('RGB', (16, 16), 'orange').save(output, format='JPEG')
    return {'event_id': str(uuid4()), 'type': 'smoke_fire', 'title': 'Test smoke',
            'occurred_at': '2026-10-17T04:00:00+00:00', 'pose': None, 'map_key': 'test-map',
            'evidence': {'validation': 'not_evaluated'},
            'snapshot_base64': base64.b64encode(output.getvalue()).decode()}


def test_retry_saves_one_incident_and_one_notification_per_recipient(seeded_db, tmp_path):
    db = seeded_db
    robot = db.scalar(select(Robot))
    storage = LocalStorageService(str(tmp_path))
    value = event()
    first = ingest_event(db, robot, value, storage)
    ident = first.id
    db.commit()
    before = db.scalars(select(Notification).where(Notification.ref_id == ident)).all()
    again = ingest_event(db, robot, value, storage)
    db.commit()
    assert again.id == ident
    assert len(db.scalars(select(Incident).where(Incident.id == ident)).all()) == 1
    assert len(db.scalars(select(Notification).where(Notification.ref_id == ident)).all()) == len(before)
    assert storage.get(f'incidents/{ident}/snapshot.jpg')
    assert '定位不可用' in again.location


def test_failed_evidence_write_does_not_create_incident(seeded_db):
    class BrokenStorage:
        def put(self, *args, **kwargs):
            raise OSError('disk full')
    db = seeded_db
    before = len(db.scalars(select(Incident)).all())
    with pytest.raises(OSError):
        ingest_event(db, db.scalar(select(Robot)), event(), BrokenStorage())
    db.rollback()
    assert len(db.scalars(select(Incident)).all()) == before


def test_bad_image_cannot_be_recorded_as_complete(seeded_db, tmp_path):
    value = event()
    value['snapshot_base64'] = base64.b64encode(b'not a jpeg').decode()
    with pytest.raises(Exception):
        ingest_event(seeded_db, seeded_db.scalar(select(Robot)), value, LocalStorageService(str(tmp_path)))
    seeded_db.rollback()
