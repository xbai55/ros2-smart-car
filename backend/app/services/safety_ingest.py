"""Pull the vehicle outbox; acknowledge only after evidence and database commit."""
import asyncio
import base64
from datetime import datetime, timezone
from io import BytesIO
import json
import logging
import math
from uuid import UUID, NAMESPACE_URL, uuid5

from PIL import Image
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from ..core.config import settings
from ..db.session import SessionLocal
from ..gateway.robot_gateway import RobotGateway
from ..models import AppSetting, Incident, Robot, User
from .ops import notify_users
from .storage import get_storage

pipeline_status = {'state': 'starting', 'message': '等待连接车端异常队列'}
logger = logging.getLogger(__name__)


def get_vehicle_url(db):
    value = db.scalar(select(AppSetting).where(AppSetting.key == 'robot_web_url'))
    return (value.value if value else settings.robot_web_url).rstrip('/')


def ingest_event(db, robot, event, storage=None):
    event_id = str(UUID(event['event_id']))
    ident = str(uuid5(NAMESPACE_URL, f'safety:{robot.id}:{event_id}'))
    existing = db.get(Incident, ident)
    if existing:
        # This ID was committed only after its image was saved.
        return existing
    category = event['type']
    if category not in {'smoke_fire', 'fallen_person', 'blocked_passage'}:
        raise ValueError('未知异常类型')
    occurred = datetime.fromisoformat(event['occurred_at'].replace('Z', '+00:00'))
    if occurred.tzinfo is None:
        raise ValueError('异常时间缺少时区')
    encoded = event['snapshot_base64']
    if not isinstance(encoded, str) or len(encoded) > 6 * 1024 * 1024:
        raise ValueError('异常图片过大')
    jpeg = base64.b64decode(encoded, validate=True)
    with Image.open(BytesIO(jpeg)) as image:
        if image.format != 'JPEG' or image.width * image.height > 16_000_000:
            raise ValueError('现场图片须为有效 JPEG')
        image.verify()
    evidence = event.get('evidence') or {}
    serialized = json.dumps({**evidence, 'source_event_id': event_id, 'run_id': event.get('run_id'),
                             'pose': event.get('pose'), 'map_key': event.get('map_key')}, ensure_ascii=False, allow_nan=False)
    if len(serialized) > 20000:
        raise ValueError('异常证据字段过大')
    pose = event.get('pose')
    localized = (isinstance(pose, dict) and pose.get('ok') and
                 all(type(pose.get(k)) in (int, float) and math.isfinite(pose[k]) for k in ('x', 'y')))
    location = f"地图{event.get('map_key', '')} ({pose['x']:.2f}, {pose['y']:.2f}) m" if localized else '定位不可用，需核对现场'
    key = f'incidents/{ident}/snapshot.jpg'
    (storage or get_storage()).put(key, jpeg, content_type='image/jpeg')
    item = Incident(id=ident, type=category, severity='critical' if category == 'smoke_fire' else 'warning',
                    robot_id=robot.id, task_id=event.get('task_id'), title=str(event.get('title') or '巡检发现异常')[:255],
                    description='车端专项识别与持续确认产生；请查看现场证据并人工核实。', location=location[:255],
                    media_keys=json.dumps([key]), image_url=f'/api/v1/media/object/{key}', evidence=serialized,
                    occurred_at=occurred.astimezone(timezone.utc))
    db.add(item)
    db.flush()
    users = [u for u in db.scalars(select(User)).all() if u.active and {'incidents.read', 'notifications.read'} <= u.permissions]
    notify_users(db, kind='incident', title=item.title, body=item.location, ref_id=ident, users=users)
    return item


async def poll_once(session_factory=SessionLocal):
    with session_factory() as db:
        url = get_vehicle_url(db)
        target = db.scalar(select(AppSetting).where(AppSetting.key == 'safety_robot_id'))
        robots = db.scalars(select(Robot)).all()
        robot = db.get(Robot, target.value) if target else robots[0] if len(robots) == 1 else None
        if not url or not robot:
            pipeline_status.update(state='unavailable', message='需要配置车端地址与唯一的异常上报小车')
            return
        async with RobotGateway._client(4.) as client:
            response = await client.get(url + '/api/safety/events')
            response.raise_for_status()
            events = response.json()['events']
            if not isinstance(events, list) or len(events) > 20:
                raise ValueError('车端异常批次无效')
            acknowledged = []
            errors = []
            for event in events:
                try:
                    ingest_event(db, robot, event)
                    db.commit()
                    acknowledged.append(event['event_id'])
                except IntegrityError:
                    db.rollback()
                    ident = str(uuid5(NAMESPACE_URL, f"safety:{robot.id}:{str(UUID(event['event_id']))}"))
                    if db.get(Incident, ident):
                        acknowledged.append(event['event_id'])
                    else:
                        errors.append('数据库写入失败，等待补传')
                except Exception as exc:
                    db.rollback()
                    errors.append(str(exc))
            if acknowledged:
                result = await client.post(url + '/api/safety/events/ack', json={'event_ids': acknowledged})
                result.raise_for_status()
            pipeline_status.update(state='degraded' if errors else 'running', message='；'.join(errors) if errors else '异常证据同步正常')


async def run_safety_ingest():
    while True:
        try:
            await poll_once()
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            pipeline_status.update(state='unavailable', message='车端证据同步未成功，队列将在恢复后补传')
            logger.debug('Safety ingestion unavailable: %s', exc)
        await asyncio.sleep(2.)
