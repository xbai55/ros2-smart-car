import asyncio
import json
from types import SimpleNamespace
from uuid import uuid4

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from app.db.base import Base
from app.models import AssistantSession, AssistantTurn, AssistantToolOperation, SystemProblem, Notification
from app.services import assistant_operations as ops
from app.services.assistant_tools import Arguments, VisionSettings, ControlExecution, Proposal, TOOLS, LogQuery
from app.services.system_health import evaluate, observe_problems, provider_status


@pytest.fixture
def db_scope():
    engine = create_engine('sqlite://')
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        session = AssistantSession(id=str(uuid4()), user_id='user')
        db.add(session)
        turn = AssistantTurn(id=str(uuid4()), session_id=session.id, client_id=str(uuid4()), prompt='停止小车')
        db.add(turn)
        db.commit()
        token = ops.current_turn.set({'turn_id': turn.id, 'session_id': session.id})
        user = SimpleNamespace(id='user', active=True, permissions={'assistant.use', 'robots.read', 'robots.control'})
        try:
            yield db, user, turn
        finally:
            ops.current_turn.reset(token)
    engine.dispose()


def test_stop_is_durable_and_not_replayed(db_scope, monkeypatch):
    db, user, turn = db_scope
    calls = []
    async def stop(*_):
        calls.append(1)
        return {'stationary_confirmed': True}
    from app.api.routes import robots
    monkeypatch.setattr(robots, 'robot_stop', stop)
    binding = ops.vehicle_binding(db)
    first = asyncio.run(ops.run_tool('stop_robot', Arguments(), db, user, binding))
    second = asyncio.run(ops.run_tool('stop_robot', Arguments(), db, user, binding))
    assert first == second and first['state'] == 'completed'
    assert len(calls) == 1
    assert len(db.scalars(select(AssistantToolOperation)).all()) == 1


def test_lost_stop_response_stays_unconfirmed_without_resend(db_scope, monkeypatch):
    db, user, turn = db_scope
    calls = []
    async def stop(*_):
        calls.append(1)
        raise TimeoutError()
    from app.api.routes import robots
    monkeypatch.setattr(robots, 'robot_stop', stop)
    binding = ops.vehicle_binding(db)
    with pytest.raises(TimeoutError):
        asyncio.run(ops.run_tool('stop_robot', Arguments(), db, user, binding))
    result = asyncio.run(ops.run_tool('stop_robot', Arguments(), db, user, binding))
    assert result['state'] == 'unconfirmed' and len(calls) == 1


@pytest.mark.parametrize('prompt', ['为什么不动', '只分析日志，不要停止', '例如停止小车', '假设让小车停止'])
def test_diagnostic_questions_do_not_authorize_stop(prompt):
    with pytest.raises(ValueError):
        ops.require_request('stop_robot', prompt, Arguments())


def test_configuration_needs_explicit_values_and_action():
    args = VisionSettings(component='safety', settings={'models': [{'id': 'fall', 'confidence': .25}]})
    ops.require_request('update_vision_settings', '把倒地阈值设置为0.25', args)
    with pytest.raises(ValueError):
        ops.require_request('update_vision_settings', '查询倒地阈值', args)
    with pytest.raises(ValueError):
        ops.require_request('update_vision_settings', '把倒地阈值设置为0.5', args)
    with pytest.raises(ValueError):
        ops.require_request('control_execution', '暂停任务', ControlExecution(execution_id='x', action='resume', version=1))


def test_health_current_state_does_not_use_historical_errors():
    previous = dict(provider_status)
    provider_status.update(state='ready')
    try:
        ctx = {'available': True, 'telemetry': {'lidar': {'ok': True}, 'navigation': {'state': 'succeeded'}}}
        issues = evaluate(ctx, {'available': True, 'camera': {'frame_age_ms': 20},
                          'yoloe': {'state': 'running'}, 'safety': {'state': 'disabled'}}, {'status': 'ready'})
        assert not issues
        ctx['telemetry']['lidar']['ok'] = False
        assert 'sensor.lidar' in evaluate(ctx, {'available': True}, {'status': 'ready'})
    finally:
        provider_status.update(previous)


def test_problem_debounce_recovery_and_no_incident(db_scope):
    db, _, _ = db_scope
    issue = {'sensor.lidar': {'code': 'sensor.lidar', 'message': '雷达异常', 'impact': '导航', 'suggestion': '检查'}}
    for _ in range(2):
        observe_problems(db, 'robot', issue)
    row = db.scalar(select(SystemProblem))
    assert row.state == 'pending'
    observe_problems(db, 'robot', issue)
    assert row.state == 'active'
    for _ in range(4):
        observe_problems(db, 'robot', {})
    assert row.state == 'active'
    observe_problems(db, 'robot', {})
    assert row.state == 'resolved'
    from app.models import Incident
    assert db.scalars(select(Incident)).all() == []


def test_extended_tools_and_existing_draft_are_available():
    assert {'execute_plan', 'propose_plan', 'get_system_health', 'query_system_logs',
            'inspect_camera_frame', 'get_vision_status', 'control_execution',
            'stop_robot', 'update_vision_settings', 'recover_vision'} <= TOOLS.keys()


def test_permissions_are_not_elevated(db_scope):
    from fastapi import HTTPException
    db, user, turn = db_scope
    user.permissions.remove('robots.control')
    with pytest.raises(HTTPException) as exc:
        asyncio.run(ops.run_tool('stop_robot', Arguments(), db, user, ops.vehicle_binding(db)))
    assert exc.value.status_code == 403
    assert not db.scalars(select(AssistantToolOperation)).all()


@pytest.mark.parametrize('accepted', [False, True])
def test_execute_uses_existing_acceptance_gate_and_one_execution(db_scope, monkeypatch, accepted):
    from app.models import Robot, AssistantExecution
    from app.services import assistant_execution, assistant_tools
    db, user, turn = db_scope
    turn.prompt = '向前前进10厘米'
    db.add(Robot(id='r-001', name='test robot', serial='test-serial'))
    db.commit()
    binding = ops.vehicle_binding(db)
    async def propose(*_):
        return {'robot_id': binding[0], 'steps': [{'action': 'move_relative', 'distance_m': .1,
                'resources': [], 'capability': {'fingerprint': 'test-fingerprint'}}]}
    monkeypatch.setattr(assistant_tools, 'propose', propose)
    monkeypatch.setattr(assistant_execution, 'capability_snapshot', lambda *_: {'capabilities': {
        'move_relative': {'executable': accepted, 'supported': True, 'ready': True, 'fingerprint': 'test-fingerprint'}}})
    args = Proposal(steps=[{'action': 'move_relative', 'distance_m': .1}])
    result = asyncio.run(ops.run_tool('execute_plan', args, db, user, binding))
    rows = db.scalars(select(AssistantExecution)).all()
    if accepted:
        assert result['state'] == 'accepted' and len(rows) == 1
        assert asyncio.run(ops.run_tool('execute_plan', args, db, user, binding)) == result
        assert len(db.scalars(select(AssistantExecution)).all()) == 1
    else:
        assert result['state'] == 'rejected' and not rows
        assert '验收' in result['error']


def test_log_tool_uses_shared_visibility_redaction_paging_and_time_bounds(db_scope, tmp_path, monkeypatch):
    from app.services import diagnostics
    db, user, _ = db_scope
    user.permissions.update({'diagnostics.read', 'patrol.read', 'missions.read'})
    store = diagnostics.DiagnosticStore(tmp_path/'diagnostics.sqlite3')
    store.init()
    store.write([{'event_id': name, 'occurred_at': diagnostics.utc(), 'source': 'host',
                  'module': 'camera', 'service': 'test', 'event_type': kind, 'reason_code': 'failed',
                  'context': {'password': 'secret', 'controller_id': 'private-id'}, 'level': 'ERROR'}
                 for name, kind in [('a', 'camera.state'), ('b', 'vision.state'), ('private', 'assistant.model')]])
    monkeypatch.setattr(diagnostics, 'store', store)
    result = asyncio.run(ops.run_tool('query_system_logs', LogQuery(limit=1), db, user, ops.vehicle_binding(db)))
    assert len(result['items']) == 1 and result['has_more']
    assert 'secret' not in json.dumps(result) and 'controller_id' not in result['items'][0]['context']
    second = asyncio.run(ops.run_tool('query_system_logs', LogQuery(limit=1, cursor=result['next_cursor'], start=result['start'], end=result['end']), db, user, ops.vehicle_binding(db)))
    assert len(second['items']) == 1 and not second['has_more']
    assert result['items'][0]['event_id'] != second['items'][0]['event_id']
    from datetime import datetime, timedelta, timezone
    from fastapi import HTTPException
    with pytest.raises(HTTPException):
        asyncio.run(ops.run_tool('query_system_logs', LogQuery(start=datetime.now(timezone.utc)-timedelta(days=15)),
                                db, user, ops.vehicle_binding(db)))


def test_independent_image_provider_requires_explicit_configuration(monkeypatch):
    from app.services import assistant_provider as provider
    monkeypatch.delenv(provider.PROFILE_ENV, raising=False)
    for name in ('ASSISTANT_VISION_BASE_URL', 'ASSISTANT_VISION_MODEL', 'ASSISTANT_VISION_API_KEY', 'ASSISTANT_SUPPORTS_IMAGES'):
        monkeypatch.delenv(name, raising=False)
    with pytest.raises(provider.ProviderUnavailable):
        provider.configured_vision_provider()
    monkeypatch.setenv('ASSISTANT_VISION_BASE_URL', 'https://vision.example/v1')
    monkeypatch.setenv('ASSISTANT_VISION_MODEL', 'vision-model')
    monkeypatch.setenv('ASSISTANT_VISION_API_KEY', 'test-only-key')
    assert provider.configured_vision_provider().model == 'vision-model'
