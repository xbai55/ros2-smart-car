"""Fixed, authenticated maintenance operations; never a shell or motion interface."""
import base64
import json
import math
import threading
import time
from uuid import uuid4


TERMINAL = {'idle', 'completed', 'cancelled', 'failed', 'finished', 'not_found'}


def require_stationary(node):
    status = node.store.snapshot()
    odom = status.get('odom') or {}
    age = node.ros_status_age_sec()
    values = [odom.get('linear_speed_xy'), odom.get('angular_speed'), odom.get('odom_age_sec')]
    if (status.get('mode') != 'stop' or age is None or not 0 <= age < .5
            or odom.get('ok') is not True
            or any(type(v) not in (float, int) or not math.isfinite(v) for v in values)
            or not 0 <= values[2] < .5 or abs(values[0]) >= .01 or abs(values[1]) >= .02):
        raise RuntimeError('需要新鲜里程计确认小车已停止')
    runner = getattr(node, 'navigation_tasks', None)
    vision = getattr(node, 'vision_service', None)
    if runner and runner.snapshot().get('state') not in TERMINAL:
        raise RuntimeError('请先结束活动任务')
    if vision and vision.search_snapshot().get('state') not in TERMINAL:
        raise RuntimeError('请先结束搜索任务')


class VisionAdmin:
    def __init__(self, node, camera):
        self.node, self.camera = node, camera
        self.lock = threading.Lock()
        self.receipts = {}
        self.component_states = {}

    def status(self):
        def snapshot(name):
            service = getattr(self.node, name, None)
            return service.snapshot() if service else {'state': 'unavailable'}
        worker = getattr(self.node, 'safety_vision', None)
        config = {}
        if worker and worker.config_path.is_file():
            from .safety_vision import load_config
            try:
                config = load_config(worker.config_path)
            except (OSError, ValueError) as exc:
                config = {'error': str(exc)}
        # Do not expose model paths as writable settings.
        settings = {k: config[k] for k in ('enabled', 'confirm_sec', 'clear_sec') if k in config}
        settings['models'] = [{k: s.get(k) for k in ('id', 'enabled', 'confidence', 'class_map', 'sha256')}
                              for s in config.get('models', [])]
        camera = self.camera.diagnostics() if self.camera and hasattr(self.camera, 'diagnostics') else {'running': False}
        yoloe = snapshot('vision_service')
        sink = getattr(self.node, 'diagnostic_log', None)
        for name, state in [('camera', 'error' if camera.get('error') else 'running' if camera.get('running') else 'idle'), ('yoloe', yoloe.get('state'))]:
            if sink and self.component_states.get(name) != state:
                sink.emit('camera.state' if name == 'camera' else 'vision.state', name + '_' + str(state),
                          level='ERROR' if state in {'error', 'degraded'} else 'INFO')
            self.component_states[name] = state
        return {'camera': camera, 'yoloe': yoloe,
                'safety': snapshot('safety_vision'), 'safety_settings': settings,
                'config_error': config.get('error'), 'received_at': time.time()}

    def frame(self):
        snap = self.camera.frame_snapshot(timeout=.8, max_age=2)
        if not snap:
            raise RuntimeError('没有两秒内的新鲜画面')
        import cv2
        import numpy as np
        frame = cv2.imdecode(np.frombuffer(snap['jpeg'], dtype=np.uint8), cv2.IMREAD_COLOR)
        if frame is None:
            raise RuntimeError('画面解码失败')
        scale = min(1., 1280 / max(frame.shape[:2]))
        if scale < 1:
            frame = cv2.resize(frame, (round(frame.shape[1]*scale), round(frame.shape[0]*scale)))
        ok, jpeg = cv2.imencode('.jpg', frame)
        if not ok or time.time() - snap['captured_at'] > 2:
            raise RuntimeError('画面编码失败或已过期')
        return {'captured_at': snap['captured_at'], 'sequence': snap['sequence'],
                'age_ms': snap['age_ms'], 'mime': 'image/jpeg',
                'jpeg_base64': base64.b64encode(jpeg).decode()}

    def mutate(self, operation, payload):
        key = payload.get('operation_id')
        if not isinstance(key, str) or len(key) != 64 or any(c not in '0123456789abcdef' for c in key):
            raise ValueError('缺少操作标识')
        body = {k: v for k, v in payload.items() if k != 'operation_id'}
        encoded = json.dumps([operation, body], sort_keys=True)
        if not self.lock.acquire(blocking=False):
            raise RuntimeError('视觉维护正在进行')
        try:
            if key in self.receipts:
                previous, result = self.receipts[key]
                if previous != encoded:
                    raise ValueError('重复操作不能改变参数')
                return result
            if len(self.receipts) >= 256:
                raise RuntimeError('维护操作记录已满，请由管理员检查服务')
            require_stationary(self.node)
            self.node.vision_maintenance_active = True
            result = {'state': 'unconfirmed', 'message': '维护结果未确认，请查询状态，不重复操作'}
            self.receipts[key] = (encoded, result)
            if operation == 'settings':
                result = self._settings(body)
            elif operation == 'recover':
                result = self._recover(body)
            else:
                raise ValueError('未知维护操作')
            self.receipts[key] = (encoded, result)
            return result
        finally:
            self.node.vision_maintenance_active = False
            self.lock.release()

    def _restart_safety(self, worker, config=None):
        with worker.config_lock:
            if worker.snapshot()['pending_in_memory']:
                raise RuntimeError('尚有未落盘证据，不能重启')
            worker.stop_event.set()
            worker.thread.join(timeout=5)
            if worker.thread.is_alive():
                raise RuntimeError('旧识别线程尚未退出，未启动新线程')
            if worker.snapshot()['pending_in_memory']:
                raise RuntimeError('结束推理后仍有未落盘证据，不能重启')
            if config is not None:
                from .navigation_tasks import _write_record
                _write_record(worker.config_path, config)
            worker._state(state='starting', models=[], detections=[], capabilities={})
            worker.stop_event = threading.Event()
            worker.thread = threading.Thread(target=worker._run, args=(worker.config_path,), daemon=True,
                                             name='inspection-vision')
            worker.thread.start()

    def _settings(self, body):
        if set(body) != {'component', 'settings'} or not isinstance(body['settings'], dict):
            raise ValueError('视觉设置格式无效')
        value = body['settings']
        if body['component'] == 'yoloe':
            self.node.vision_service.configure(value)
        elif body['component'] == 'safety':
            if set(value) - {'enabled', 'confirm_sec', 'clear_sec', 'models'}:
                raise ValueError('不能修改权重或映射')
            worker = self.node.safety_vision
            config = json.loads(worker.config_path.read_text(encoding='utf-8'))
            from .safety_vision import load_config
            # Resolve IDs against the saved configuration without requiring healthy weights.
            normalized = load_config(worker.config_path, {**config, 'enabled': False})
            config['models'] = normalized['models']
            for patch in value.get('models', []):
                if not isinstance(patch, dict) or set(patch) - {'id', 'enabled', 'confidence'}:
                    raise ValueError('不能修改权重或映射')
                spec = next((s for s in config['models'] if s['id'] == patch.get('id')), None)
                if spec is None:
                    raise ValueError('模型标识不存在')
                spec.update(patch)
            config.update({k: v for k, v in value.items() if k != 'models'})
            if type(config.get('enabled')) is not bool:
                raise ValueError('识别开关须为布尔值')
            load_config(worker.config_path, config)
            self._restart_safety(worker, config)
        else:
            raise ValueError('未知视觉组件')
        return {'state': 'accepted', 'message': '设置已保存，请核对运行状态', 'status': self.status()}

    def _recover(self, body):
        if set(body) != {'target'} or body['target'] not in {'camera', 'yoloe', 'safety'}:
            raise ValueError('未知恢复目标')
        worker = getattr(self.node, 'safety_vision', None)
        if vision_error := (getattr(self.node, 'vision_service', None).snapshot().get('evidence_error') if getattr(self.node, 'vision_service', None) else None):
            raise RuntimeError('视觉证据保存失败，需先检查存储，不能恢复')
        if worker and worker.snapshot()['pending_in_memory']:
            raise RuntimeError('尚有未落盘证据，不能恢复')
        target = body['target']
        vision = getattr(self.node, 'vision_service', None)
        if vision:
            from .navigation_tasks import _write_record
            with vision.lock:
                vision.config['recovery_epoch'] = uuid4().hex
                _write_record(vision.config_path, vision.config)
                vision.status.update(mobile_ready=False, recovery_epoch=vision.config['recovery_epoch'])
        if target == 'camera':
            self.camera.close()
            thread = self.camera._worker
            if thread and thread.is_alive():
                thread.join(timeout=5)
                if thread.is_alive():
                    raise RuntimeError('旧摄像头线程尚未退出，不能重复打开设备')
        elif target == 'yoloe':
            if not vision:
                raise RuntimeError('视觉服务未初始化')
            with vision.lock:
                if vision.process:
                    vision.process.terminate()
                    vision.process.join(timeout=5)
                    if vision.process.is_alive():
                        raise RuntimeError('旧推理进程尚未退出')
                vision.process = None
                from .vision_service import replace_latest
                import queue
                for channel in (vision.requests, vision.responses):
                    try:
                        while True:
                            channel.get_nowait()
                    except queue.Empty:
                        pass
                vision.sequence = -1
                vision.status.update(state='loading', detections=[])
        else:
            if not worker:
                raise RuntimeError('专项服务未初始化')
            self._restart_safety(worker)
        fresh = self.camera.frame_snapshot(timeout=2, max_age=.5)
        deadline = time.monotonic() + 5
        while target != 'camera' and time.monotonic() < deadline:
            status = (vision if target == 'yoloe' else worker).snapshot()
            if status.get('state') in {'running', 'error', 'disabled', 'unavailable'}:
                break
            time.sleep(.1)
        status = self.status()
        ready = bool(fresh) and (target == 'camera' or status['yoloe' if target == 'yoloe' else 'safety'].get('state') == 'running')
        return {'state': 'completed' if ready else 'unavailable', 'status': status,
                'message': '视觉恢复完成，移动搜索需重新验证' if ready else '恢复后仍不可用，请核对状态'}
