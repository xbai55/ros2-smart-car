import io
import json
from contextlib import closing
from datetime import datetime, timedelta, timezone
from zipfile import ZipFile

import pytest

from app.services import diagnostics


def raw(ident, **overrides):
    return {
        'event_id': ident, 'occurred_at': diagnostics.utc(), 'source': 'host',
        'module': 'controller', 'service': 'test', 'event_type': 'motion.zero',
        'reason_code': 'operator_stop', 'trace_id': 'trace-one', 'robot_id': 'r-001',
        'level': 'WARN', 'context': {'final': [0, 0, 0], 'password': 'private',
                                    'target': 'sk-secret', 'controller_id': 'controller-1'},
        'exception': {'type': 'RuntimeError', 'frames': ['control.py:10:run']}, **overrides,
    }


@pytest.fixture
def index(tmp_path, monkeypatch):
    result = diagnostics.DiagnosticStore(tmp_path / 'diagnostics.sqlite3')
    result.init()
    result.write([])
    monkeypatch.setattr(diagnostics, 'store', result)
    return result


def auth(login, name='admin'):
    return {'Authorization': 'Bearer ' + login(name, name + '123')}


def test_query_roles_trace_and_safe_export(client, login, index):
    index.write([raw('stop-one'), raw('stop-one'),
                 raw('private-one', execution_id='other', event_type='assistant.execution')])
    admin, operator, auditor = (auth(login, role) for role in ('admin', 'operator', 'auditor'))
    prefix = '/api/v1/diagnostics'
    assert client.get(prefix + '/events', headers=auditor).status_code == 403
    detail = client.get(prefix + '/events/stop-one', headers=operator).json()
    assert detail['context']['final'] == [0, 0, 0]
    assert not {'exception', 'controller_id'} & detail['context'].keys()
    assert 'exception' not in detail
    assert 'private' not in json.dumps(detail)
    assert detail['context']['target'] is None
    assert client.get(prefix + '/events/private-one', headers=operator).status_code == 404
    response = client.get(prefix + '/traces/trace-one?trace_id=wrong', headers=admin)
    assert {e['event_id'] for e in response.json()['items']} == {'stop-one', 'private-one'}
    end = datetime.now(timezone.utc) + timedelta(seconds=1)
    payload = {'start': (end - timedelta(hours=1)).isoformat(), 'end': end.isoformat()}
    assert client.post(prefix + '/exports', json=payload, headers=operator).status_code == 403
    package = client.post(prefix + '/exports', json=payload, headers=admin)
    assert package.status_code == 200, package.text[:200]
    with ZipFile(io.BytesIO(package.content)) as archive:
        assert 'jetson' in json.loads(archive.read('manifest.json'))['missing']
        assert b'sk-secret' not in archive.read('events.ndjson')


def test_late_insert_and_filter_bound_cursor(client, login, index):
    index.write([raw('first')])
    headers = auth(login, 'operator')
    path = '/api/v1/diagnostics/events?robot_id=r-001'
    page = client.get(path, headers=headers).json()
    index.write([raw('late', occurred_at=diagnostics.utc(datetime.now().timestamp() - 60))])
    delta = client.get(path, params={'robot_id': 'r-001', 'after': page['after']}, headers=headers).json()
    assert [row['event_id'] for row in delta['items']] == ['late']
    reset = client.get(path, params={'robot_id': 'r-001', 'after': page['after'], 'level': 'INFO'}, headers=headers)
    assert reset.json()['reset']


def test_queue_bounds_checkpoint_and_expiry(index):
    for i in range(1200):
        index.offer(raw('host-' + str(i), event_type='host.started'))
    assert index.queues[0].qsize() == 1024
    assert index.health['dropped'] == 176
    index.offer(raw('critical'))
    assert index.queues[1].qsize() == 1
    index.write([raw('broken', occurred_at='invalid'), raw('good')], ('vehicle:test', '{}'))
    with closing(index.connect()) as db, db:
        assert db.execute("SELECT value FROM metadata WHERE key='vehicle:test'").fetchone()[0] == '{}'
        db.execute("UPDATE events SET observed_at='2000-01-01T00:00:00.000Z'")
    index.write([])
    with closing(index.connect()) as db:
        assert db.execute('SELECT count(*) FROM events').fetchone()[0] == 0
    assert index.health['invalid'] == 1


def test_vehicle_cursor_resumes_and_rebind_quarantines(index, monkeypatch):
    import asyncio
    from types import SimpleNamespace
    from app.services.diagnostics import vehicle

    robot = ['robot-one']
    instance = 'b' * 32
    seen = []

    async def pull(_gateway, cursors):
        seen.append(cursors)
        return {'instance_id': instance, 'events': [raw('vehicle-one', schema_version=1)],
                'cursors': {'controller-1': 'vehicle-one'}, 'gaps': [], 'invalid': 0}

    async def single_iteration(_delay):
        raise asyncio.CancelledError

    monkeypatch.setattr(vehicle, 'binding', lambda: (robot[0], 'http://fixture'))
    monkeypatch.setattr(vehicle, 'pull', pull)
    monkeypatch.setattr(vehicle, 'asyncio', SimpleNamespace(to_thread=asyncio.to_thread, sleep=single_iteration))

    for _ in range(2):
        with pytest.raises(asyncio.CancelledError):
            asyncio.run(vehicle.ingest_vehicle(index))
    assert seen == [{}, {'controller-1': 'vehicle-one'}]
    robot[0] = 'robot-two'
    with pytest.raises(asyncio.CancelledError):
        asyncio.run(vehicle.ingest_vehicle(index))
    assert index.health['vehicle']['status'] == 'quarantined'
    with closing(index.connect()) as db:
        assert [row[0] for row in db.execute('SELECT robot_id FROM events')] == ['robot-one']
