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

from ..db.session import SessionLocal
from ..gateway.robot_gateway import RobotGateway, get_robot_gateway
from ..models import AppSetting, FallReview, Incident, Robot, User
from .assistant_provider import fall_review_enabled
from .ops import notify_users
from .storage import get_storage
from .incident_reports import record_coverage
from .robot_context import vehicle_binding

pipeline_status = {'state': 'starting', 'message': '等待连接车端异常队列'}
logger = logging.getLogger(__name__)


def get_vehicle_url(db):
    return get_robot_gateway(vehicle_binding(db)[1]).base_url


def ingest_event(db, robot, event, storage=None):
    if event.get('type') == 'suspected_clutter':
        # Compatibility with old vehicle queues: acknowledge without creating
        # a new incident, saving media or sending a notification.
        UUID(event['event_id'])
        pipeline_status['suppressed_observations'] = pipeline_status.get('suppressed_observations', 0) + 1
        return None
    event_id = str(UUID(event['event_id']))
    ident = str(uuid5(NAMESPACE_URL, f'safety:{robot.id}:{event_id}'))
    existing = db.get(Incident, ident)
    if existing:
        # This ID was committed only after its image was saved.
        return existing
    category = event['type']
    if category not in {'smoke_fire', 'fallen_person', 'blocked_passage', 'suspected_clutter', 'target_found'}:
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
    if category in {'smoke_fire','fallen_person'}:
        from .safety_alert_settings import read_thresholds
        score=(event.get('evidence') or {}).get('confidence')
        threshold=getattr(read_thresholds(db),category).candidate
        if type(score) not in (int,float) or not math.isfinite(score) or not 0 <= score <= 1 or score < threshold:
            return None
    evidence = event.get('evidence') or {}
    serialized = json.dumps({**evidence, 'source_event_id': event_id, 'run_id': event.get('run_id'),
                             'pose': event.get('pose'), 'map_key': event.get('map_key'),
                             'model_sha256':event.get('model_sha256'),
                             'position_kind':event.get('position_kind')}, ensure_ascii=False, allow_nan=False)
    if len(serialized) > 20000:
        raise ValueError('异常证据字段过大')
    pose = event.get('pose')
    localized = (isinstance(pose, dict) and pose.get('ok') and
                 all(type(pose.get(k)) in (int, float) and math.isfinite(pose[k]) for k in ('x', 'y')))
    location = f"地图{event.get('map_key', '')} ({pose['x']:.2f}, {pose['y']:.2f}) m" if localized else '定位不可用，需核对现场'
    key = f'incidents/{ident}/snapshot.jpg'
    (storage or get_storage()).put(key, jpeg, content_type='image/jpeg')
    reviewing = category in {'fallen_person', 'smoke_fire'} and fall_review_enabled()
    raw_key = ''
    if reviewing and event.get('raw_snapshot_base64'):
        raw_encoded = event['raw_snapshot_base64']
        if not isinstance(raw_encoded, str) or len(raw_encoded) > 6 * 1024 * 1024:
            raise ValueError('原始图片过大')
        raw = base64.b64decode(raw_encoded, validate=True)
        with Image.open(BytesIO(raw)) as image:
            if image.format != 'JPEG' or image.width * image.height > 16_000_000:
                raise ValueError('原始图片须为有效 JPEG')
            image.verify()
        raw_key = f'incidents/{ident}/original.jpg'
        (storage or get_storage()).put(raw_key, raw, content_type='image/jpeg')
    description=('YOLOE 持续识别到现场物品；占道未确认，请结合图片人工核实。'
                 if category=='suspected_clutter' else
                 '车端目标搜索记录；位置为车辆位置，不是目标坐标。'
                 if category=='target_found' else
                 '车端专项识别与持续确认产生；请查看现场证据并人工核实。')
    item = Incident(id=ident, type=category, severity='critical' if category == 'smoke_fire' else 'warning',
                    robot_id=robot.id, task_id=event.get('task_id'), title=str(event.get('title') or '巡检发现异常')[:255],
                    description=description, location=location[:255],
                    media_keys=json.dumps([key]), image_url=f'/api/v1/media/object/{key}', evidence=serialized,
                    occurred_at=occurred.astimezone(timezone.utc))
    db.add(item)
    db.flush()
    if reviewing:
        job = FallReview(incident_id=ident, raw_key=raw_key)
        db.add(job)
        if raw_key:
            item.media_keys = json.dumps([key, raw_key])
            item.title = '视觉候选，等待 DS 复核（未告警）'
            item.description = '本地检测通过阈值与持续确认，单张现场原图等待云端复核。'
        else:
            from .fall_review import finish_review
            finish_review(db, job, 'failed', error='车端未提供未标注原图，未调用 DS，请人工核实')
        return item
    users = [u for u in db.scalars(select(User)).all() if u.active and {'incidents.read', 'notifications.read'} <= u.permissions]
    notify_users(db, kind='incident', title=item.title, body=item.location, ref_id=ident, users=users)
    return item


async def poll_once(session_factory=SessionLocal):
    with session_factory() as db:
        robot_id, address = vehicle_binding(db)
        url = get_robot_gateway(address).base_url
        target = db.scalar(select(AppSetting).where(AppSetting.key == 'safety_robot_id'))
        robot = db.get(Robot, robot_id) if target is None or target.value == robot_id else None
        if not url or not robot:
            pipeline_status.update(state='unavailable', message='需要配置车端地址与唯一的异常上报小车')
            return
        try:
            await _pull_events(db, url, robot)
        except Exception:
            db.rollback()
            record_coverage(db, robot.id, "interrupted")
            raise
        record_coverage(db, robot.id, "observed" if pipeline_status["state"] == "running" else "interrupted")


async def _pull_events(db, url, robot):
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
