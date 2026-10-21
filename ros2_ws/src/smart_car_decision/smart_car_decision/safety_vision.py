"""Inspection inference consumes the web camera's newest frame, never the USB device.

Specialist weights are explicit local files. Missing weights never fall back to COCO.
"""
import hashlib
import json
import math
from pathlib import Path
import threading
import time
from uuid import uuid4
from datetime import datetime, timezone

from .navigation_config import map_key
from .safety_events import DetectionTracks, EventGate, SafetyOutbox, corridor_candidate

TITLES = {'smoke_fire': '发现疑似烟火', 'fallen_person': '发现疑似人员倒地', 'blocked_passage': '发现通道持续占用'}


def load_config(path, value=None):
    path = Path(path).expanduser()
    config = json.loads(path.read_text(encoding='utf-8')) if value is None else value
    if not isinstance(config, dict):
        raise ValueError('巡检识别配置须为对象')
    for field, low, high, default in [('rate_hz', .2, 15, 5), ('confirm_sec', .2, 30, 2), ('clear_sec', 1, 300, 10),
                                      ('camera_fov_deg', 20, 150, 70), ('camera_yaw_offset', -math.pi, math.pi, 0)]:
        value = config.get(field, default)
        if type(value) not in (int, float) or not math.isfinite(value) or not low <= value <= high:
            raise ValueError(f'{field} 超出允许范围')
        config[field] = value
    if not isinstance(config.get('models', []), list) or len(config.get('models', [])) > 2:
        raise ValueError('专项模型配置须为最多两个模型的列表')
    for spec in config.get('models', []):
        if not isinstance(spec, dict) or not isinstance(spec.get('path'), str) or not isinstance(spec.get('class_map'), dict):
            raise ValueError('专项模型配置无效')
        model_path = Path(spec['path']).expanduser()
        model_path = model_path if model_path.is_absolute() else path.parent / model_path
        if not model_path.is_file() or model_path.suffix not in {'.pt', '.engine', '.onnx'}:
            raise ValueError(f'专项模型文件不存在：{model_path}')
        spec['path'] = str(model_path.resolve())
        if not spec.get('class_map') or any(v not in TITLES or v == 'blocked_passage' for v in spec['class_map'].values()):
            raise ValueError('专项模型须显式配置烟火/倒地标签映射')
        if not .05 <= float(spec.get('confidence', .5)) <= 1:
            raise ValueError('模型置信阈值无效')
    zones = config.get('corridors', [])
    if not isinstance(zones, list) or len(zones) > 30 or any(not isinstance(z, dict) for z in zones):
        raise ValueError('通道配置须为最多30个区域的列表')
    ids = set()
    for zone in zones:
        if not zone.get('id') or zone['id'] in ids or not zone.get('map_key'):
            raise ValueError('通道需要唯一标识与地图版本')
        ids.add(zone['id'])
        if not all(type(zone.get(k, default)) in (int, float) and math.isfinite(zone.get(k, default)) for k, default in [('axis_yaw', 0.), ('required_free_width_m', .65)]):
            raise ValueError('通道方向或通行宽度无效')
        if not .2 <= zone.get('required_free_width_m', .65) <= 3.:
            raise ValueError('通道所需净宽无效')
        polygon = zone.get('polygon', [])
        if len(polygon) < 3 or len(polygon) > 30 or any(len(p) != 2 or not all(type(v) in (int, float) and math.isfinite(v) for v in p) for p in polygon):
            raise ValueError('通道边界须为至少三个地图米制坐标点')
    return config


class SafetyVisionWorker:
    def __init__(self, node, camera, config_path, outbox_path):
        self.node, self.camera = node, camera
        self.config_path = Path(config_path).expanduser()
        self.config_lock = threading.Lock()
        self.outbox = SafetyOutbox(outbox_path)
        self.lock, self.stop_event = threading.RLock(), threading.Event()
        self.scan_points, self.scan_at = [], 0.
        self.pending = []
        self.status = {'state': 'starting', 'message': '正在读取专项识别配置', 'models': [], 'detections': [], 'updated_at': None}
        self.thread = threading.Thread(target=self._run, args=(config_path,), daemon=True, name='inspection-vision')

    def snapshot(self):
        with self.lock:
            return {**json.loads(json.dumps(self.status)), 'pending_in_memory': len(self.pending)}

    def update_scan(self, points):
        with self.lock:
            self.scan_points, self.scan_at = points, time.monotonic()

    def start(self):
        self.thread.start()

    def close(self):
        self.stop_event.set()
        self.thread.join(timeout=3)

    def corridors(self):
        if not self.config_path.is_file():
            return []
        return json.loads(self.config_path.read_text(encoding='utf-8')).get('corridors', [])

    def configure_corridors(self, zones):
        if not isinstance(zones, list) or len(zones) > 30:
            raise ValueError('通道区域最多30个')
        with self.config_lock:
            if self.pending:
                raise RuntimeError('现场证据尚未落盘，请先恢复磁盘空间，避免重启识别丢失待保存画面')
            config = json.loads(self.config_path.read_text(encoding='utf-8')) if self.config_path.is_file() else {'enabled': True, 'models': []}
            config['corridors'] = zones
            load_config(self.config_path, config)
            self.stop_event.set()
            self.thread.join(timeout=5)
            if self.thread.is_alive():
                raise RuntimeError('识别正在结束当前推理，请稍后重试')
            from .navigation_tasks import _write_record
            _write_record(self.config_path, config)
            self.stop_event = threading.Event()
            self.thread = threading.Thread(target=self._run, args=(self.config_path,), daemon=True, name='inspection-vision')
            self.thread.start()
            return zones

    def _state(self, **values):
        with self.lock:
            self.status.update(values)

    def _run(self, config_path):
        try:
            config = load_config(config_path)
            if not config.get('enabled', False):
                self._state(state='disabled', message='巡检识别未启用')
                return
            import cv2
            import numpy as np
            models = []
            if config.get('models'):
                from ultralytics import YOLO
                for spec in config['models']:
                    model = YOLO(spec['path'])
                    names = set(model.names.values())
                    if not set(spec['class_map']).issubset(names):
                        raise ValueError(f"模型标签不匹配：{spec['path']}")
                    digest = hashlib.sha256(Path(spec['path']).read_bytes()).hexdigest()
                    models.append((spec, model, digest))
            if not models and not config.get('corridors'):
                self._state(state='unavailable', message='尚未配置烟火/倒地专项权重或通道区域')
                return
            self._state(models=[{'path': Path(s['path']).name, 'sha256': d, 'classes': s['class_map'],
                                 'validation': s.get('validation', 'not_evaluated')} for s, _, d in models])
            self._state(capabilities={category: any(category in s['class_map'].values() for s, _, _ in models)
                                      for category in ('smoke_fire', 'fallen_person')}, configured_corridors=len(config.get('corridors', [])))
            gate = EventGate(config['confirm_sec'], config['clear_sec'], max(1., 2. / config['rate_hz']))
            tracks = DetectionTracks(config['clear_sec'])
            pending = self.pending
            sequence = None
            while not self.stop_event.is_set():
                try:
                    while pending:
                        self.outbox.put(*pending[0])
                        pending.pop(0)
                    started = time.monotonic()
                    status = self.node.store.snapshot()
                    if status.get('mode') not in {'stop', 'navigation'}:
                        gate.reset_pending()
                        self._state(state='idle', message='巡检识别等待停止或导航模式', detections=[])
                        self.stop_event.wait(.5)
                        continue
                    snap = self.camera.frame_snapshot(after_sequence=sequence, timeout=.3, max_age=.5)
                    if not snap:
                        gate.reset_pending()
                        self._state(state='degraded', message='没有新鲜摄像头画面', detections=[])
                        self.stop_event.wait(.2)
                        continue
                    sequence = snap['sequence']
                    frame = cv2.imdecode(np.frombuffer(snap['jpeg'], dtype=np.uint8), cv2.IMREAD_COLOR)
                    if frame is None:
                        raise ValueError('摄像头 JPEG 无法解码')
                    candidates = []
                    grid = self.node.map_snapshot.snapshot()
                    identity = map_key(grid) if grid else ''
                    pose = status.get('map_pose', {})
                    pose_fresh = self.node.ros_status_age_sec() is not None and self.node.ros_status_age_sec() <= 2.5
                    for spec, model, digest in models:
                        result = model.predict(frame, imgsz=640, conf=float(spec.get('confidence', .5)),
                                               device=config.get('device', '0'), verbose=False)[0]
                        for box in result.boxes or []:
                            label = result.names[int(box.cls[0])]
                            category = spec['class_map'].get(label)
                            if category:
                                coords = [float(v) for v in box.xyxy[0].tolist()]
                                candidates.append({'type': category, 'label': label,
                                                   'confidence': float(box.conf[0]), 'box': coords, 'model_sha256': digest,
                                                   'validation': spec.get('validation', 'not_evaluated'), 'method': 'specialist_yolo11_temporal'})
                                cv2.rectangle(frame, tuple(map(int, coords[:2])), tuple(map(int, coords[2:])), (0, 80, 255), 2)
                                cv2.putText(frame, label, (int(coords[0]), max(18, int(coords[1]))), cv2.FONT_HERSHEY_SIMPLEX, .6, (0, 80, 255), 2)
                    candidates = tracks.update(candidates, time.monotonic())
                    with self.lock:
                        points, scan_at = self.scan_points, self.scan_at
                    # Points have already been transformed into map at the scan timestamp.
                    if pose_fresh and pose.get('ok'):
                        heading = pose.get('yaw', 0.) + float(config.get('camera_yaw_offset', 0.))
                        half_fov = math.radians(float(config.get('camera_fov_deg', 70.))) / 2
                        points = [(x,y) for x,y in points if abs(math.atan2(math.sin(math.atan2(y-pose['y'],x-pose['x'])-heading), math.cos(math.atan2(y-pose['y'],x-pose['x'])-heading))) < half_fov]
                    candidates += corridor_candidate(points, config.get('corridors', []), {'ok': True, 'x': 0., 'y': 0., 'yaw': 0.},
                                                       identity, now=time.monotonic(), scan_at=scan_at, pose_fresh=pose_fresh and pose.get('ok', False))
                    # A slow model must not confirm a stale scene after the car has moved.
                    if time.time() - snap['captured_at'] > 2:
                        gate.reset_pending()
                        self._state(state='degraded', message='识别画面超时，请降低模型负载', detections=[])
                        continue
                    ok, jpeg = cv2.imencode('.jpg', frame, [cv2.IMWRITE_JPEG_QUALITY, 85])
                    if not ok:
                        gate.reset_pending()
                        continue
                    now = time.monotonic()
                    for candidate in gate.update(candidates, now):
                        runner = getattr(self.node, 'navigation_tasks', None)
                        task = runner.snapshot() if runner else {}
                        pending.append(({'event_id': str(uuid4()), 'type': candidate['type'], 'title': TITLES[candidate['type']],
                                         'occurred_at': datetime.fromtimestamp(snap['captured_at'], timezone.utc).isoformat(),
                                         'task_id': task.get('task_id') if task.get('state') not in {'idle', 'completed', 'failed', 'cancelled'} else None,
                                         'run_id': task.get('run_id'), 'map_key': identity,
                                         'pose': pose if pose_fresh and pose.get('ok') else None,
                                         'evidence': candidate}, jpeg.tobytes()))
                    while pending:
                        self.outbox.put(*pending[0])
                        pending.pop(0)
                    self._state(state='running', message='巡检识别运行中；报警不改变巡航', detections=candidates,
                                updated_at=snap['captured_at'], inference_ms=round((time.monotonic() - started) * 1000, 1))
                    self.stop_event.wait(max(0., 1. / config['rate_hz'] - (time.monotonic() - started)))
                except Exception as exc:
                    gate.reset_pending()
                    self._state(state='degraded', message=f'识别或证据保存失败，将重试：{exc}', detections=[])
                    self.stop_event.wait(1.)
        except FileNotFoundError:
            self._state(state='unavailable', message='尚未配置巡检专项模型与通道区域')
        except Exception as exc:
            self._state(state='error', message=f'巡检识别不可用：{exc}', detections=[])
            self.node.get_logger().error(f'巡检识别：{exc}')
