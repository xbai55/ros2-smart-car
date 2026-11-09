"""Manual browser acceptance fixture with the production API and isolated data."""
import os
import secrets
import sys
import tempfile
from contextlib import asynccontextmanager
from pathlib import Path

import uvicorn
from fastapi.staticfiles import StaticFiles

ROOT = Path(__file__).resolve().parents[1]


def build(directory):
    os.environ.update(
        DATABASE_URL='sqlite:///' + (Path(directory) / 'fixture.sqlite3').as_posix(),
        STORAGE_LOCAL_DIR=str(Path(directory) / 'storage'), JWT_SECRET=secrets.token_hex(32),
        REDIS_ENABLED='false', MINIO_ENDPOINT='', ROBOT_WEB_URL='', ROBOT_GATEWAY_URL='',
    )
    sys.path.insert(0, str(ROOT / 'backend'))
    from sqlalchemy import select
    from app.db.session import SessionLocal
    from app.main import app
    from app.models import AssistantEvent, AssistantExecution, AssistantPlan, AssistantSession, Robot, User
    from app.seed import seed
    from app.services import diagnostics as diag

    seed()
    with SessionLocal() as db:
        user = db.scalar(select(User).where(User.username == 'operator'))
        db.add(Robot(id='fixture-robot', name='模拟车辆', serial='DIAG'))
        db.add(AssistantSession(id='fixture-session', user_id=user.id))
        db.flush()
        db.add(AssistantPlan(id='fixture-plan', session_id='fixture-session', robot_id='fixture-robot',
                             content='{}', digest='fixture', trace_id='fixture-assistant', expires_at=0))
        db.flush()
        db.add(AssistantExecution(id='fixture-execution', plan_id='fixture-plan', robot_id='fixture-robot',
                                  user_id=user.id, state='failed'))
        db.add(AssistantEvent(user_id=user.id, execution_id='fixture-execution',
                              kind='execution.failed', payload='{}'))
        db.commit()

    @asynccontextmanager
    async def lifespan(_):
        index = diag.DiagnosticStore(Path(directory) / 'diagnostics.sqlite3')
        index.init()
        diag.store = index
        base = {'source': 'jetson', 'module': 'controller', 'service': 'smart_car_decision',
                'occurred_at': diag.utc(), 'robot_id': 'fixture-robot', 'trace_id': 'fixture-stop',
                'episode_id': 'fixture-episode'}
        index.write([
            {**base, 'event_id': 'zero', 'event_type': 'motion.zero', 'reason_code': 'control_lease_expired',
             'level': 'WARN', 'context': {'first': 'control_lease_expired', 'winner': 'control_lease_expired',
                                          'final': [0, 0, 0], 'mode': 'navigation', 'lease_blocked': True}},
            {**base, 'event_id': 'stationary', 'event_type': 'motion.stationary', 'reason_code': 'fresh_odometry',
             'level': 'INFO', 'context': {'linear_speed': 0.0, 'angular_speed': 0.0}},
            {**base, 'source': 'host', 'event_id': 'agent-model', 'event_type': 'assistant.model',
             'trace_id': 'fixture-assistant', 'episode_id': None, 'reason_code': 'provider_returned'},
            {**base, 'source': 'host', 'event_id': 'agent-failed', 'event_type': 'assistant.execution',
             'trace_id': 'fixture-assistant', 'episode_id': None, 'execution_id': 'fixture-execution',
             'reason_code': 'reconciliation_required', 'level': 'ERROR'},
        ])
        index.start()
        try:
            yield
        finally:
            index.close()
            diag.store = None

    app.router.lifespan_context = lifespan
    app.mount('/', StaticFiles(directory=ROOT / 'web-console/dist', html=True))
    return app


if __name__ == '__main__':
    with tempfile.TemporaryDirectory(prefix='diagnostics-fixture-', ignore_cleanup_errors=True) as root:
        uvicorn.run(build(root), host='127.0.0.1', port=int(sys.argv[1]), log_level='warning')
