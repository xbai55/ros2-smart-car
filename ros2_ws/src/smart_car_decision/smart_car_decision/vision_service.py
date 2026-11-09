"""Shared YOLOE supervisor and search task coordinator; never publishes cmd_vel."""
import asyncio
import copy
import hashlib
import json
import math
import multiprocessing as mp
import queue
import threading
import time
from pathlib import Path
from uuid import uuid4
from .diagnostic_log import request_ids
from datetime import datetime, timezone

from .navigation_tasks import _write_record
from .component_manifest import component_manifest
from .navigation_config import map_key
from .safety_events import DetectionTracks, EventGate, SafetyOutbox
from .vision_search import CLUTTER, Confirmation, associate_clutter, targets, vocabulary_id
from .yoloe_worker import replace_latest, run

BUILD = 'vision-search-4.0.0'
TERMINAL = {'idle','cancelled','not_found','finished'}


class VisionService:
    def __init__(self, node, camera, directory, start_worker=True):
        self.node, self.camera = node, camera
        self.root = Path(directory).expanduser()
        self.root.mkdir(parents=True,exist_ok=True)
        self.config_path = self.root/'vision.json'
        self.config = {'enabled':True,'clutter_enabled':True,'clutter_prompts':CLUTTER,
                       'imgsz':640,'model_path':str(self.root/'models/yoloe-11s-seg.pt')}
        self.config_error = None
        try:
            if self.config_path.exists():
                self.config.update(json.loads(self.config_path.read_text()))
            self._validate_config(self.config)
        except Exception as exc:
            self.config_error = str(exc)
        self.lock = threading.RLock()
        self.search = {'state':'idle','message':'等待创建搜索任务','run_id':None}
        previous = self.root/'search.json'
        if previous.exists():
            node.set_mode('stop')
            try:
                self.search = json.loads(previous.read_text(encoding='utf-8'))
                archived = self._read_run(self.search['run_id']) if self.search.get('run_id') else None
                if archived:
                    self.search = archived
                if self.search['state'] not in TERMINAL:
                    self._state('fault', '车端重启，旧搜索已停止，请结束后重新创建')
            except Exception:
                self.search.update(state='fault',message='搜索记录损坏，保持停车')
        self.status = {'supported':True,'stationary_search_supported':True,'state':'unavailable','message':'等待本地模型','build_id':BUILD,'detections':[], 'mobile_ready':False,'imgsz':self.config['imgsz']}
        if self.config_error:self.status.update(state='error',message='视觉配置无效：'+self.config_error)
        self.confirm = Confirmation()
        self.context = mp.get_context('spawn')
        self.requests, self.responses = self.context.Queue(1), self.context.Queue(1)
        self.process = None
        self.stop = threading.Event()
        self.at = self.result_at = 0.
        self.sequence = -1
        self.protocol_version = 0
        self.desired_gate = 'hold'
        self.settled = None
        self.wait_absence = False
        self.absent_since = None
        self.route_id = None
        self.loop = None
        self.clutter_gate = EventGate(2.,10.,.6)
        self.clutter_tracks = DetectionTracks(expiry_sec=10.)
        self.outbox = SafetyOutbox(self.root/'vision-events.sqlite3')
        self.scan = ([],0.)
        self.thread = threading.Thread(target=self._run,daemon=True,name='vision-supervisor')
        if start_worker:self.thread.start()

    @staticmethod
    def _validate_config(value):
        if type(value.get('enabled')) is not bool or type(value.get('clutter_enabled')) is not bool:
            raise ValueError('识别开关须为布尔值')
        if value.get('imgsz') not in (416,640):
            raise ValueError('输入尺寸须为 416 或 640')
        prompts=value.get('clutter_prompts')
        if not isinstance(prompts,list) or len(prompts)>12:
            raise ValueError('杂物词表最多 12 项')
        for prompt in prompts:
            targets([{'name':prompt,'prompt':prompt}])

    def snapshot(self):
        with self.lock:
            return copy.deepcopy(self.status)

    def search_snapshot(self):
        with self.lock:
            return copy.deepcopy(self.search)

    def _run_path(self, ident):
        if not isinstance(ident, str) or not 1 <= len(ident) <= 128:
            raise ValueError('搜索请求标识无效')
        return self.root / 'search-runs' / (hashlib.sha256(ident.encode()).hexdigest() + '.json')

    def _read_run(self, ident):
        path = self._run_path(ident)
        try:
            return json.loads(path.read_text(encoding='utf-8'))
        except FileNotFoundError:
            return None

    def search_snapshot_for(self, ident=None):
        with self.lock:
            if ident is None or ident == self.search.get('run_id'):
                return self.search_snapshot()
            result = self._read_run(ident)
            if result is None:
                raise ValueError('车端没有此搜索记录')
            # An archived run cannot hold the current search lock.
            if result['state'] not in TERMINAL:
                result.update(state='fault', message='历史搜索已中止', version=result.get('version', 0) + 1)
            return result

    def settings(self):
        with self.lock:
            return copy.deepcopy(self.config)

    def _stationary(self):
        s=self.node.store.snapshot(); odom=s.get('odom',{})
        age=self.node.ros_status_age_sec()
        return (s.get('mode')=='stop' and not s.get('emergency_stop') and age is not None and age<.5
                and odom.get('ok') and odom.get('odom_age_sec',99)<.5
                and abs(odom.get('linear_speed_xy',1))<.01 and abs(odom.get('angular_speed',1))<.02)

    def configure(self, value):
        with self.lock:
            if not self._stationary() or self.search['state'] not in TERMINAL:
                raise RuntimeError('请先停止小车并结束搜索任务')
            if set(value)-{'enabled','clutter_enabled','clutter_prompts','imgsz'}:
                raise ValueError('不支持的视觉设置')
            config={**self.config,**value}; self._validate_config(config)
            _write_record(self.config_path, config)
            self.config,self.config_error=config,None
            self.status['imgsz']=config['imgsz']
            self.status['mobile_ready']=False
            if self.process is not None and not self.process.is_alive():
                self.process.join(timeout=1)
                self.process=None
            return self.settings()

    def _state(self, state, message, **values):
        self.search.update(state=state,message=message,version=self.search.get('version', 0)+1,**values)
        try:
            if self.search.get('run_id'):
                _write_record(self._run_path(self.search['run_id']), self.search)
            _write_record(self.root/'search.json',self.search)
        except OSError as exc:
            self.search['persistence_error']=str(exc)
            self.desired_gate='hold'
            self.search['state']='fault'
            self.node.set_mode('stop')

    def _gate(self, op):
        ack=getattr(self.node,'search_ack',{})
        if not ack.get('controller_id') or not self.search.get('run_id'):
            return
        self.protocol_version+=1
        self.node.publish_search_control({'controller_id':ack['controller_id'],'run_id':self.search['run_id'],
            'version':self.protocol_version,'op':op,'reason':self.search['message'],
            'diagnostic':request_ids.get()})

    def _hold(self, state, message):
        self.desired_gate='hold'
        self._gate('hold')
        self.node.set_mode('stop')
        self._pause_route()
        self._state(state,message)

    def _pause_route(self):
        runner=getattr(self.node,'navigation_tasks',None)
        if runner and self.route_id and runner.snapshot().get('run_id')==self.route_id:
            if runner.snapshot()['state'] in {'planning','running','returning','dwelling'} and self.loop:
                asyncio.run_coroutine_threadsafe(runner.action({'run_id':self.route_id,'action':'pause'}),self.loop)

    def _certified(self):
        try:
            certificate=json.loads((self.root/'vision-performance.json').read_text())
            return (certificate.get('build_id')==BUILD and certificate.get('imgsz')==self.config['imgsz']
                    and certificate.get('source_sha256')==component_manifest()['source_sha256']
                    and self.status.get('state')=='running'
                    and certificate.get('model_sha256')==self.status.get('model_sha256')
                    and bool(certificate.get('model_sha256'))
                    and certificate.get('duration_sec',0)>=600 and certificate.get('effective_hz',0)>=3
                    and certificate.get('age_p95_sec',99)<=.5 and certificate.get('control_overruns',1)==0
                    and certificate.get('joint_navigation_video') is True)
        except (ValueError,OSError,KeyError):
            return False

    async def start(self,payload):
        ident = payload.get('run_id') if 'run_id' in payload else uuid4().hex
        self._run_path(ident)
        request = {key: value for key, value in payload.items() if key != 'control_lease'}
        fingerprint = hashlib.sha256(json.dumps(request, sort_keys=True, allow_nan=False).encode()).hexdigest()
        with self.lock:
            previous = self.search if ident == self.search.get('run_id') else self._read_run(ident)
            if previous is not None:
                if previous.get('request_fingerprint') not in {fingerprint, None} or (
                        previous.get('request_fingerprint') is None and previous['state'] != 'cancelled'):
                    raise RuntimeError('同一搜索标识的请求已变化')
                return self.search_snapshot_for(ident)
            if self.search['state'] not in TERMINAL or not self._stationary():
                raise RuntimeError('请先停止小车并结束现有搜索任务')
            runner=getattr(self.node,'navigation_tasks',None)
            nav=getattr(self.node,'navigation',None)
            if (runner and runner.active) or (nav and nav.snapshot().get('state') in {'starting','running'}):
                raise RuntimeError('已有导航或运输任务，不能接管')
            selected=targets(payload.get('targets'))
            travel=payload.get('travel','stationary')
            if travel not in {'stationary','patrol'}:
                raise ValueError('搜索方式须为静止观察或地图巡逻')
            if not self.config['enabled'] or self.status.get('state')!='running' or (
                    travel=='patrol' and not self.status.get('mobile_ready')):
                raise RuntimeError('模型或板端联合性能尚未就绪')
            if travel=='patrol':
                if not runner or not runner._lease_valid(payload.get('control_lease')):
                    raise RuntimeError('巡逻搜索需要有效的车辆控制租约')
                avoidance=self.node.avoidance_service.snapshot()
                if not avoidance.get('confirmed') or not avoidance.get('available'):
                    raise RuntimeError('雷达或控制器尚未就绪')
            self.loop=asyncio.get_running_loop()
            self.search={'run_id':ident,'request_fingerprint':fingerprint,'targets':selected,
                         'travel':travel,'control_lease':payload.get('control_lease'),'created_at':time.time()}
            self.confirm=Confirmation(); self.protocol_version=0
            self.desired_gate='arm'; self.route_id=ident if travel=='patrol' else None
            self._state('preparing','准备目标词表')
            if self.search['state'] != 'preparing':
                raise RuntimeError('搜索记录无法保存')
            self._gate('arm')
        try:
            if travel=='patrol':
                if not runner:
                    raise RuntimeError('地图巡逻不可用')
                spec={**payload.get('patrol',{}),'run_id':ident,'task_id':ident,'kind':'patrol','cycles':1,'return_to_start':False}
                route=await runner.create(spec)
                if route.get('state') != 'prepared':
                    raise RuntimeError('搜索路线已取消或不可用')
            # Require a new inference on this exact vocabulary before movement.
            deadline=time.monotonic()+15
            while time.monotonic()<deadline:
                with self.lock:
                    ready=(self.status.get('run_id')==self.search['run_id'] and time.monotonic()-self.result_at<.5)
                    ack=getattr(self.node,'search_ack',{})
                    armed=(ack.get('run_id')==ident and ack.get('active') and ack.get('held')
                           and 0 <= time.monotonic()-ack.get('received_at',0) <= .5)
                    if self.search.get('run_id') != ident or self.search['state']!='preparing':
                        raise RuntimeError(self.search['message'])
                if ready and armed:
                    break
                await asyncio.sleep(.05)
            else:
                raise RuntimeError('词表预热或控制器停车确认超时')
            with self.lock:
                if self.search.get('run_id') != ident or self.search['state']!='preparing':raise RuntimeError('搜索启动已取消')
                if travel=='stationary':
                    if not self._stationary():
                        raise RuntimeError('车辆静止状态已失效')
                    self.at=time.monotonic()
                    self.desired_gate='hold'
                    self._state('searching','正在静止观察')
                    return self.search_snapshot()
                self._gate('resume')
                self.desired_gate='heartbeat'
            await asyncio.sleep(.15)
            ack=getattr(self.node,'search_ack',{})
            if ack.get('run_id')!=ident or ack.get('held'):
                raise RuntimeError('控制器未确认搜索接管')
            with self.lock:
                if self.search.get('run_id') != ident or self.search['state']!='preparing':raise RuntimeError('搜索启动已取消')
                self.at=time.monotonic(); self._state('searching','正在搜索')
                if self.search['state'] != 'searching':
                    raise RuntimeError('搜索状态无法保存')
            if travel=='patrol':
                await runner.action({'run_id':ident,'action':'start','control_lease':payload.get('control_lease')})
            return self.search_snapshot_for(ident)
        except (Exception, asyncio.CancelledError):
            with self.lock:
                if self.search.get('run_id') == ident and self.search['state'] not in TERMINAL:
                    self._hold('fault','搜索启动失败，请结束后重试')
            raise

    async def action(self,value):
        with self.lock:
            ident, action = value.get('run_id'), value.get('action')
            if ident!=self.search.get('run_id'):
                if action == 'cancel':
                    result = self._read_run(ident)
                    if result is not None:
                        return self.search_snapshot_for(ident)
                    result = {'run_id':ident,'state':'cancelled','version':1,'message':'未派发的搜索已取消'}
                    _write_record(self._run_path(ident), result)
                    return result
                raise RuntimeError('搜索任务已变化，请刷新')
            if action in {'cancel','finish'} and self.search['state'] in TERMINAL:
                return self.search_snapshot()
            route_id = self.route_id
            if action=='pause' and self.search['state']=='searching':
                self._hold('paused','搜索已暂停')
            elif action in {'cancel','finish'}:
                self._hold('cancelled' if action=='cancel' else 'finished','搜索已结束')
                # Keep latch until physical standstill; supervisor releases later.
            elif action in {'resume','continue'} and self.search['state'] in {'paused','found'}:
                stationary = self.search['travel']=='stationary'
                if not self.config['enabled'] or not self._stationary() or (
                        not stationary and not self.status.get('mobile_ready')) or time.monotonic()-self.result_at>.5:
                    raise RuntimeError('请等待车辆静止和视觉恢复')
                self.confirm=Confirmation(); self.wait_absence=True; self.absent_since=None
                if stationary:
                    ack = getattr(self.node,'search_ack',{})
                    if ack.get('run_id') != ident or not ack.get('active') or not ack.get('held') or time.monotonic()-ack.get('received_at',0)>.5:
                        raise RuntimeError('控制器停车锁尚未确认')
                    self.at=time.monotonic()
                    self._state('searching','继续静止观察')
                    return self.search_snapshot()
                if not self.node.navigation_tasks._lease_valid(value.get('control_lease')):
                    raise RuntimeError('巡逻搜索需要新的车辆控制租约')
                self._gate('resume'); self.desired_gate='heartbeat'
                self.at=time.monotonic(); self._state('searching','继续搜索，等待原目标离开画面',
                                                     control_lease=value.get('control_lease'))
            else:
                raise RuntimeError('当前阶段不支持此操作')
        if action in {'cancel','finish'} and route_id:
            runner=self.node.navigation_tasks
            await runner.action({'run_id':route_id,'task_id':route_id,'kind':'patrol','action':'cancel'})
        if action in {'resume','continue'}:
            await asyncio.sleep(.15)
            ack=getattr(self.node,'search_ack',{})
            with self.lock:
                if self.search.get('run_id') != ident or self.search['state'] != 'searching':
                    raise RuntimeError('搜索恢复已取消')
                if ack.get('run_id') != ident or ack.get('held'):
                    self._hold('fault','恢复搜索未获控制器确认')
                    raise RuntimeError('控制器未确认恢复')
            try:
                await self.node.navigation_tasks.action({'run_id':route_id,'action':'resume','control_lease':value.get('control_lease')})
            except Exception:
                with self.lock:
                    if self.search.get('run_id') == ident and self.search['state'] == 'searching':
                        self._hold('fault','巡逻恢复失败，已停止搜索')
                raise
        return self.search_snapshot_for(ident)

    def _result(self,item):
        if 'error' in item:
            self.status.update(state='error',message=item['error'],mobile_ready=False)
            return
        prompts=self._prompts(); version=vocabulary_id(prompts)
        if item['version']!=version or item['run_id']!=self.search.get('run_id'):
            return
        now=time.monotonic()
        if not 0<=now-item['captured_mono']<=.5:
            return
        self.result_at=now
        self.status.update(state='running',message='识别运行中',detections=item['detections'],
            model_sha256=item['model_sha256'],frame_age_ms=(now-item['captured_mono'])*1000,
            inference_ms=item['inference_ms'],vocabulary_version=version,run_id=item['run_id'],updated_at=time.time())
        selected={v['prompt'] for v in self.search.get('targets',[])}
        matches=[v for v in item['detections'] if v['label'] in selected]
        if self.search['state']=='searching':
            if self.wait_absence:
                last_key=self.search.get('evidence',{}).get('evidence',{}).get('key')
                previous_visible=any(v['key']==last_key for v in matches) if last_key else bool(matches)
                self.absent_since=now if not previous_visible and self.absent_since is None else self.absent_since
                if previous_visible:self.absent_since=None
                if self.absent_since is not None and now-self.absent_since>=2:self.wait_absence=False
            else:
                found=self.confirm.observe(item['sequence'],item['captured_mono'],now,matches)
                if found:
                    self.settled=None
                    self.stopping_at=now
                    self._hold('stopping','已识别目标，等待车辆静止')
                    self.search['evidence']=self._save(item,found,'target_found')
        if self.config['clutter_enabled']:
            candidates=[]
            for detection in item['detections']:
                if detection['label'] not in self.config['clutter_prompts']:continue
                association=associate_clutter(detection['box'],self.scan[0],self.config.get('calibration'),
                    item['image_size'],item['captured_at'],self.scan[1])
                detection['passage']='疑似占道' if association else '占道未确认'
                # Visual observations can be reported without claiming a
                # calibrated obstacle distance or a confirmed blocked passage.
                if detection['confidence']>=.5:
                    candidates.append({**detection,'association':association,
                                       'passage_confirmed':False,'confirmation_sec':2.})
            # The GPU tracker expires after 2 seconds. Reassociate report
            # candidates through brief misses instead of alerting on a new ID.
            candidates=self.clutter_tracks.update(candidates,now)
            for event in self.clutter_gate.update(candidates,now):
                self._save(item,event,'suspected_clutter')
        # Annotated output shares the existing camera overlay path.
        self._overlay={'jpeg':item['annotated'],'sequence':item['sequence'],'captured_mono':item['captured_mono']}
        self.node.annotated_frames.update(item['annotated'],now=item['captured_mono'])

    def frame_snapshot(self):
        with self.lock:
            value=getattr(self,'_overlay',None)
            age=time.monotonic()-value['captured_mono'] if value else 99
            return {'jpeg':value['jpeg'],'sequence':value['sequence'],'age_ms':age*1000} if 0<=age<=.5 else None

    def _save(self,item,detection,kind):
        ident=uuid4().hex
        title=('发现目标' if kind=='target_found' else
               '疑似杂物占道' if detection.get('association') else '发现物品（占道未确认）')
        event={'event_id':ident,'type':kind,'title':title,
            'occurred_at':datetime.fromtimestamp(item['captured_at'],timezone.utc).isoformat(),
            'run_id':self.search.get('run_id'),'evidence':detection,
            'model_sha256':item['model_sha256'],'targets':self.search.get('targets',[]),
            'pose':self.node.store.snapshot().get('map_pose'), 'position_kind':'vehicle_not_target'}
        maps=getattr(self.node,'map_snapshot',None)
        grid=maps.snapshot() if maps else None
        event['map_key']=map_key(grid) if grid else None
        try:
            directory=self.root/'vision-evidence';directory.mkdir(exist_ok=True)
            # Unique immutable files; original camera evidence accompanies annotated outbox.
            with (directory/(ident+'.jpg')).open('xb') as stream:stream.write(item['original'])
            _write_record(directory/(ident+'.json'),event)
            self.outbox.put(event,item['annotated'])
            return event
        except OSError as exc:
            event['save_error']=str(exc)
            self.status['evidence_error']=str(exc)
            return event

    def _prompts(self):
        selected=[v['prompt'] for v in self.search.get('targets',[])]
        clutter=self.config['clutter_prompts'] if self.config['clutter_enabled'] else []
        return list(dict.fromkeys(selected+clutter)) or ['object']

    def _supervise_search(self, now):
        ack = getattr(self.node, 'search_ack', {})
        stationary = self.search['travel'] == 'stationary'
        if (ack.get('run_id') != self.search['run_id'] or ack.get('active') is not True
                or not 0 <= now - ack.get('received_at', 0) <= .5
                or ack.get('held') is not stationary):
            self._hold('paused', '控制器搜索确认失效，已停止')
        elif now-self.result_at > 1:
            self._hold('paused', '视觉超时，搜索已暂停')
        elif stationary:
            if not self._stationary():
                self._hold('paused', '静止状态失效，搜索已暂停')
            elif now-self.at >= 300:
                self._hold('not_found', '静止观察结束，本次未找到目标')
        else:
            route = self.node.navigation_tasks.snapshot()
            phase = route.get('state')
            if route.get('run_id') != self.route_id or phase in {'failed','cancelled'}:
                self._hold('fault', '巡逻执行已中断')
            elif phase == 'completed':
                self._hold('not_found', '巡逻结束，本次未找到目标')
            elif phase == 'paused':
                self._hold('paused', '巡逻已暂停')
            elif self.node.store.snapshot().get('mode') != 'navigation' and now-self.at > .5:
                nav = self.node.navigation.snapshot()
                arriving = nav.get('state') == 'succeeded' and nav.get('goal_id') == route.get('goal_id')
                if self.node.store.snapshot().get('mode') != 'stop' or (
                        phase not in {'planning', 'dwelling'} and not arriving):
                    self._hold('paused', '驾驶模式变化，搜索已暂停')

    def _run(self):
        checked=0.
        while not self.stop.wait(.05):
            try:
                with self.lock:
                    now=time.monotonic()
                    if now-checked>5:
                        self.status['mobile_ready']=not self.config_error and self._certified(); checked=now
                    active=self.search['state'] in {'preparing','searching','stopping','found','paused','fault'}
                    if active:self._gate(self.desired_gate)
                    if self.search['state']=='searching':
                        self._supervise_search(now)
                    if self.search['state']=='stopping':
                        self.settled=now if self._stationary() and self.settled is None else self.settled
                        if not self._stationary():self.settled=None
                        if self.settled is not None and now-self.settled>=.5:self._state('found','已找到并停车')
                        elif now-getattr(self,'stopping_at',now)>5:self._state('fault','无法确认车辆静止，保持停车锁')
                    if self.search['state'] in TERMINAL and self.search.get('run_id') and self._stationary():
                        self._gate('release')
                    enabled=(not self.config_error and self.config['enabled'] and self.node.store.snapshot().get('mode') in {'stop','auto','navigation'})
                    if not enabled:continue
                    if self.process is None:
                        if not Path(self.config['model_path']).is_file():continue
                        self.process=self.context.Process(target=run,args=(self.config['model_path'],self.requests,self.responses),daemon=True)
                        self.process.start();self.status.update(state='loading',message='正在加载 YOLOE-11s')
                    try:
                        item=self.responses.get_nowait();self._result(item)
                    except queue.Empty:pass
                    if not self.process.is_alive():
                        self.status.update(state='error',message=self.status.get('message','推理进程退出'),mobile_ready=False)
                        continue
                    if now-getattr(self,'last_submit',0)<.2:continue
                    snap=self.camera.frame_snapshot(timeout=0,after_sequence=self.sequence,max_age=.5)
                    if snap:
                        self.sequence=snap['sequence'];self.last_submit=now
                        prompts=self._prompts()
                        replace_latest(self.requests,{**snap,'captured_mono':now-snap['age_ms']/1000,
                            'run_id':self.search.get('run_id'),'version':vocabulary_id(prompts),'prompts':prompts,'imgsz':self.config['imgsz']})
            except Exception as exc:
                with self.lock:
                    self.status.update(state='error',message=str(exc),mobile_ready=False)
                    if self.search['state']=='searching':self._hold('fault','视觉服务异常，已停止搜索')

    def close(self):
        self.stop.set();self.thread.join(timeout=3)
        if self.process:
            replace_latest(self.requests,None);self.process.join(timeout=2)
            if self.process.is_alive():self.process.terminate();self.process.join(timeout=2)
