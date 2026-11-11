"""Deterministic system problems, separate from environmental incidents."""
import asyncio
import hashlib
import json
from datetime import datetime, timezone

from sqlalchemy import select

from ..models import SystemProblem, User
from ..db.session import SessionLocal
from ..gateway import get_robot_gateway
from . import diagnostics
from .ops import notify_users
from .robot_context import vehicle_binding, robot_context_service

provider_status = {'state': 'unknown', 'observed_at': None}


def model_observed(ok):
    provider_status.update(state='ready' if ok else 'unavailable', observed_at=stamp())


def stamp():
    return datetime.now(timezone.utc).isoformat()


async def vision_status(binding):
    gateway = get_robot_gateway(binding[1])
    if not gateway.base_url:
        return {'available': False, 'reason': 'vehicle_unbound'}
    try:
        async with gateway._client(3) as client:
            response = await client.get(gateway.base_url + '/api/vision/health')
            response.raise_for_status()
            result = response.json()
            if not isinstance(result, dict):
                raise ValueError()
            return {'available': True, **result}
    except Exception:
        return {'available': False, 'reason': 'vision_status_unavailable'}


def evaluate(context, vision, log_health):
    issues = {}
    def add(code, message, impact, advice):
        issues[code] = {'code': code, 'status': 'observed', 'message': message,
                        'impact': impact, 'suggestion': advice, 'root_cause_confirmed': False}
    if not context.get('available'):
        add('vehicle.telemetry', '车端遥测不可用或已过期', '无法确认车辆实时状态或执行新任务', '检查车端服务、网络和机器凭据')
    else:
        data = context.get('telemetry') or {}
        for sensor in ('lidar', 'odom', 'tf'):
            if (data.get(sensor) or {}).get('ok') is False:
                add('sensor.'+sensor, sensor+' 状态异常', '导航或运动可能受阻', '查看对应传感器及ROS节点日志')
        navigation = data.get('navigation') or {}
        if navigation.get('state') == 'failed':
            add('navigation.failed', '当前导航失败', '本段任务无法继续', '核对定位、目标可达性及导航日志')
        if (data.get('avoidance') or {}).get('state') in {'sensor_fault', 'timeout'}:
            add('motion.blocked', '运动控制报告传感器故障或超时', '运动输出被阻断', '核对传感器时效和控制日志，勿绕过保护')
    if not vision.get('available'):
        add('vision.status', '无法读取视觉状态', '烟火、倒地和搜索能力尚未确认', '检查车端接口版本与通信')
    else:
        camera = vision.get('camera') or {}
        age = camera.get('frame_age_ms')
        if camera.get('error') or (type(age) in (int, float) and age > 2000):
            add('camera.frames', '摄像头出错或画面过期', '视觉识别没有可靠新画面', '检查摄像头连接；停止任务后可明确要求恢复摄像头')
        for name in ('yoloe', 'safety'):
            state = (vision.get(name) or {}).get('state')
            if state in {'error', 'degraded', 'unavailable'}:
                add('vision.'+name, name+' 视觉组件不可用或降级', '对应识别功能可能不可用', '查询模型状态与诊断日志，核对权重、标签及依赖')
        if (vision.get('yoloe') or {}).get('evidence_error') or (vision.get('safety') or {}).get('pending_in_memory'):
            add('vision.evidence', '视觉证据尚未保存成功', '异常照片可能只在内存中，不能恢复服务', '先检查存储，保留当前进程以免丢失证据')
        if vision.get('config_error'):
            add('vision.config', '专项视觉配置校验失败', '专项模型无法正常加载', '核对配置、权重哈希和类别映射')
    if log_health.get('status') != 'ready':
        add('diagnostics.storage', '诊断存储未就绪', '日志证据可能不完整', '检查后台诊断存储状态')
    if (log_health.get('vehicle') or {}).get('status') in {'offline', 'degraded', 'quarantined'}:
        add('diagnostics.vehicle', '车端日志同步不完整', '无法完整关联车端故障', '检查日志采集、网络及同步状态')
    if (log_health.get('vehicle') or {}).get('pose_write_failed') or (log_health.get('vehicle') or {}).get('web_write_failed'):
        add('diagnostics.write', '车端日志写入失败', '部分诊断证据缺失', '检查存储权限和可用空间，当前未采集磁盘容量')
    if provider_status['state'] == 'unavailable':
        add('assistant.provider', '最近一次模型请求失败', '助手生成回复受影响', '检查模型连接与凭据；成功调用后更新状态')
    return issues


def observe_problems(db, robot_id, issues, *, immediate=False):
    now = stamp()
    rows = {r.code: r for r in db.scalars(select(SystemProblem).where(SystemProblem.robot_id == robot_id))}
    targets = None
    def notify(row, recovered):
        nonlocal targets
        if targets is None:
            targets = [u for u in db.scalars(select(User)) if u.active and {'diagnostics.read', 'robots.read', 'notifications.read'} <= u.permissions]
        detail = json.loads(row.details)
        notify_users(db, kind='system_problem', title=('系统问题已恢复：' if recovered else '系统问题：') + detail['message'],
                     body='请在助手系统状态中查看证据与建议。', ref_id=row.id, users=targets)
    for code, detail in issues.items():
        row = rows.get(code)
        if row is None:
            row = SystemProblem(id=hashlib.sha256((robot_id+':'+code).encode()).hexdigest(), robot_id=robot_id,
                                code=code, first_seen=now, last_seen=now, details='{}', failures=0, successes=0, state='pending')
            db.add(row)
        if row.state == 'resolved':
            row.first_seen, row.failures, row.state = now, 0, 'pending'
        row.failures += 1
        row.successes, row.last_seen, row.details = 0, now, json.dumps(detail, ensure_ascii=False)
        if row.state != 'active' and (immediate or row.failures >= 3):
            row.state = 'active'
            notify(row, False)
    for code, row in rows.items():
        if code in issues or code.startswith('task.'):
            continue
        row.successes += 1
        row.failures = 0
        if row.successes >= 5 and row.state != 'resolved':
            active = row.state == 'active'
            row.state = 'resolved'
            if active:
                notify(row, True)
    db.commit()


async def health_snapshot(db, user):
    if not {'robots.read', 'diagnostics.read'} <= user.permissions:
        from fastapi import HTTPException
        raise HTTPException(403, '缺少系统诊断权限')
    binding = vehicle_binding(db)
    ctx = robot_context_service.context(binding[0], binding)
    vision = await vision_status(binding)
    logs = dict(diagnostics.store.health) if diagnostics.store else {'status': 'unavailable'}
    current = evaluate(ctx, vision, logs)
    evidence = []
    try:
        from .diagnostics.query import query, page
        from types import SimpleNamespace
        now = datetime.now(timezone.utc)
        from datetime import timedelta
        evidence = query(lambda conn: page(conn, user, SimpleNamespace(query_params={'robot_id': binding[0]}),
                                         now-timedelta(minutes=15), now, 20, None, None))['items']
    except Exception:
        pass
    rows = db.scalars(select(SystemProblem).where(SystemProblem.robot_id == binding[0]).order_by(SystemProblem.last_seen.desc()).limit(30))
    return {'robot_id': binding[0], 'observed_at': stamp(), 'vehicle_available': ctx.get('available'),
            'telemetry_received_at': ctx.get('received_at'), 'telemetry_age_sec': ctx.get('age_sec'),
            'backend': {'state': 'ready'}, 'model': dict(provider_status), 'diagnostics': logs,
            'issues': list(current.values()), 'evidence': evidence,
            'time_note': '日志可能延迟或存在车端时钟偏差，不能只按时间顺序推定因果。',
            'history': [{**json.loads(r.details), 'id': r.id, 'state': r.state,
                         'first_seen': r.first_seen, 'last_seen': r.last_seen} for r in rows],
            'unknown': ['disk_free', 'temperature'],
            'diagnostics_path': '/diagnostics'}


async def run_health_monitor():
    while True:
        try:
            with SessionLocal() as db:
                binding = vehicle_binding(db)
                ctx = robot_context_service.context(binding[0], binding)
                vision = await vision_status(binding)
                logs = dict(diagnostics.store.health) if diagnostics.store else {'status': 'unavailable'}
                observe_problems(db, binding[0], evaluate(ctx, vision, logs))
        except Exception:
            # Health monitoring must never prevent stopping or taking control.
            pass
        await asyncio.sleep(2)
