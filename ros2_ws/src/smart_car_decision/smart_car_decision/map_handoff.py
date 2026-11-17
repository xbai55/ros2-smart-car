from .service_budgets import HANDOFF_TOTAL, CAPTURE_WAIT
"""One-process, one-use pose handoff from live SLAM to a saved map."""
import copy
import hashlib
import json
import math
import threading
import time
from uuid import uuid4


class HandoffError(RuntimeError):
    def __init__(self, code, message, *, retryable=False):
        super().__init__(message)
        self.code, self.retryable = code, retryable


class MapHandoff:
    def __init__(self, node, clock=time.monotonic):
        self.node, self.clock = node, clock
        self.lock = threading.RLock()
        self.operation = threading.Lock()
        self.receipt = None

    def active(self):
        with self.lock:
            r = self.receipt
            if r and r.get('phase')=='ready': return False
            eligible = bool(r and not r.get('cancelled') and
                        (r.get('capturing') or self.clock()-r.get('at', -1000)<HANDOFF_TOTAL) and
                        not r.get('used'))
            seeded = bool(r and r.get('used') and not r.get('cancelled') and self.clock()-r.get('at', -1000)<HANDOFF_TOTAL)
        return eligible or (seeded and self.node.navigation_runtime.snapshot().get('state') != 'ready')

    def invalidate(self, code, value=None):
        # Caller holds the receipt lock. Keep the first reason, including after cleanup.
        r = self.receipt
        if not r or r.get('failure'): return
        before=r.get('odom', {})
        fields=('frame_id','stamp','x','y','yaw')
        evidence={'before':{k:before.get(k) for k in fields},
                  'after':{k:(value or {}).get(k) for k in fields}, 'phase':r.get('phase'),
                  'elapsed_sec':self.clock()-r.get('at',self.clock())}
        r.update(cancelled=True, failure={'code':code, **evidence})
        sink=getattr(self.node,'diagnostic_log',None)
        if sink:
            sink.emit('map.handoff.invalidated',code,details=evidence,level='WARN')

    def observe_odom(self, value):
        with self.lock:
            r=self.receipt
            if not r or 'odom' not in r or r.get('cancelled') or r.get('phase')=='ready': return
            b=r['odom']
            if any(type(value.get(k)) not in (int,float) or not math.isfinite(value[k]) for k in ('x','y','yaw','stamp')):
                self.invalidate('odom_invalid',value);return
            code = ('odom_frame_changed' if value.get('frame_id')!=b['frame_id'] else
                    'odom_stamp_backwards' if value['stamp']<r.get('last_stamp',b['stamp']) else
                    'position_changed' if math.hypot(value['x']-b['x'],value['y']-b['y'])>.05 else
                    'heading_changed' if abs(math.atan2(math.sin(value['yaw']-b['yaw']),math.cos(value['yaw']-b['yaw'])))>math.radians(3) else None)
            if code:self.invalidate(code,value)
            r['last_stamp']=value['stamp']

    def diagnostic(self, payload):
        with self.lock:
            r=self.receipt
            if not r or (payload.get('request_id') and payload['request_id']!=r['request_id']) or (payload.get('handoff_id') and payload['handoff_id']!=r.get('handoff_id')):
                return {'valid':False,'reason_code':'receipt_missing','retryable':False}
            return {k:copy.deepcopy(r.get(k)) for k in ('request_id','handoff_id','digest','phase','waiting_reason','failure','loaded','loading','used','seed_outcome')} | {
                'valid':not r.get('cancelled') and self.clock()-r.get('at',-1000)<HANDOFF_TOTAL,
                'remaining_sec':max(0.,HANDOFF_TOTAL-(self.clock()-r.get('at',-1000)))}

    def odom(self, require_fresh=True):
        value = dict(getattr(self.node, 'relative_odom', {}))
        age = self.clock()-value.get('received_at', -1000)+value.get('source_age_sec', 0)
        if (require_fresh and not 0 <= age <= .5) or not value.get('frame_id'):
            raise HandoffError('odom_not_ready','里程计已陈旧，等待新鲜数据',retryable=True)
        if any(type(value.get(k)) not in (int,float) or not math.isfinite(value[k]) for k in ['x','y','yaw','stamp']):
            raise RuntimeError('里程计位置无效')
        return value

    def capture(self, payload, validate):
        request_id = str(payload['request_id'])
        with self.lock:
            if self.receipt and self.receipt['request_id']==request_id:
                if self.receipt.get('cancelled'):
                    raise RuntimeError('地图准备已取消')
                return self.export()
        if not self.operation.acquire(blocking=False):
            raise RuntimeError('地图交接正在进行，请勿重复提交')
        try:
            validate()
            if self.node.mapping_restart.snapshot()['state']!='ready':
                raise RuntimeError('本轮建图尚未就绪')
            if self.node.map_snapshot.session_id!=payload['session_id']:
                raise RuntimeError('建图会话已变化')
            with self.lock:
                self.receipt={'request_id':request_id,'cancelled':False,'capturing':True,'phase':'capturing','at':self.clock()}
            self.node.set_command('stop')
            deadline, stable = self.clock()+CAPTURE_WAIT, None
            waiting_reason = 'stationary_not_ready'
            while self.clock()<deadline:
                validate()
                with self.lock:
                    if self.receipt.get('cancelled'): raise RuntimeError('地图准备已取消')
                if self.node.map_snapshot.session_id!=payload['session_id']:
                    raise RuntimeError('建图会话已变化，未复用旧位姿')
                status=self.node.store.snapshot()
                odom=status.get('odom',{})
                try:
                    capture_odom=self.odom()
                    odom_fresh=True
                except HandoffError as exc:
                    if not exc.retryable:raise
                    odom_fresh=False
                age=self.node.ros_status_age_sec()
                stopped=(odom_fresh and age is not None and 0<=age<.5 and odom.get('ok')
                         and 0<=odom.get('odom_age_sec',99)<.5
                         and abs(odom.get('linear_speed_xy',1))<.01 and abs(odom.get('angular_speed',1))<.03)
                stable=self.clock() if stopped and stable is None else stable if stopped else None
                if stable is not None and self.clock()-stable>=.5:
                    grid=self.node.map_snapshot.snapshot()
                    if grid and grid.get('session_id')!=payload['session_id']:
                        raise RuntimeError('建图会话已变化，未复用旧地图')
                    grid_age=time.time()-grid.get('updated_at',0) if grid else float('inf')
                    waiting_reason='map_not_ready'
                    if grid and 0<=grid_age<=1.5:
                        pose=copy.deepcopy(status.get('map_pose',{}))
                        updated,source_age=pose.get('updated_at'),pose.get('age_sec',0)
                        pose_age=(time.time()-updated+source_age if
                                  type(updated) in (int,float) and type(source_age) in (int,float)
                                  and math.isfinite(updated) and math.isfinite(source_age) and source_age>=0 else float('inf'))
                        waiting_reason='pose_not_ready'
                        if (pose.get('ok') and 0<=pose_age<=.5
                                and all(type(pose.get(k)) in (int,float) and math.isfinite(pose[k]) for k in ('x','y','yaw'))):
                            break
                else:
                    waiting_reason='stationary_not_ready'
                with self.lock:self.receipt['waiting_reason']=waiting_reason
                time.sleep(.05)
            else:
                messages={'stationary_not_ready':'等待停车或新鲜里程计超时，请保持静止后重试',
                          'map_not_ready':'等待本轮新鲜地图超时，请保持建图并重试',
                          'pose_not_ready':'等待本轮新鲜地图位姿超时，请检查定位变换后重试或手动定位'}
                with self.lock:self.invalidate(waiting_reason)
                raise HandoffError(waiting_reason,messages[waiting_reason])
            validate()
            digest=hashlib.sha256(json.dumps(grid,ensure_ascii=False,allow_nan=False,separators=(',',':')).encode()).hexdigest()
            with self.lock:
                if self.receipt.get('cancelled'): raise RuntimeError('地图准备已取消')
                self.receipt.update(capturing=False,snapshot=grid,digest=digest,pose=pose,odom=capture_odom,
                                    at=self.clock(),handoff_id=uuid4().hex,used=False,loaded=False,phase='captured')
            # Keep the mapping lease valid until the host receives this snapshot.
            # The host then releases that exact lease and confirms a full stop.
            return self.export()
        except Exception:
            with self.lock:
                if self.receipt and self.receipt['request_id']==request_id:
                    self.invalidate('capture_failed')
                    self.receipt['capturing']=False
            self.node.set_command('stop')
            self.node.set_mode('stop')
            raise
        finally:
            self.operation.release()

    def export(self):
        if self.receipt.get('capturing'):
            raise RuntimeError('地图交接仍在进行')
        return {k:copy.deepcopy(self.receipt[k]) for k in ['snapshot','digest','handoff_id']}

    def check(self, ident, digest=None, require_unused=False, require_fresh=True):
        with self.lock:
            r=self.receipt
            if not r or r.get('capturing') or r.get('handoff_id')!=ident or r.get('cancelled'):
                raise HandoffError((r or {}).get('failure',{}).get('code','receipt_invalid'),'自动位姿已失效：'+(r or {}).get('failure',{}).get('code','记录不存在或已取消')+'，请手动定位')
            if self.clock()-r['at']>HANDOFF_TOTAL or digest is not None and digest!=r['digest']:
                raise RuntimeError('自动位姿过期或地图已变化，请手动定位')
            if require_unused and r['used']:
                raise RuntimeError('初始位姿已经发送，不重复发送')
            value=self.odom(require_fresh);baseline=r['odom']
            if (value['frame_id']!=baseline['frame_id'] or value['stamp']<baseline['stamp'] or
                math.hypot(value['x']-baseline['x'],value['y']-baseline['y'])>.05 or
                abs(math.atan2(math.sin(value['yaw']-baseline['yaw']),math.cos(value['yaw']-baseline['yaw'])))>math.radians(3)):
                self.observe_odom(value)
                if not r.get('cancelled'):self.invalidate('odom_continuity_lost',value)
                raise HandoffError(r['failure']['code'],'交接期间位置、朝向或里程计连续性发生变化，请手动定位')
            if not r['loaded'] and not r.get('loading') and self.node.map_snapshot.session_id!=r['snapshot']['session_id']:
                raise RuntimeError('建图会话已改变')
            return copy.deepcopy(r)

    def load(self, payload):
        with self.operation:
            return self._load(payload)

    def _load(self, payload):
        r=self.check(payload['handoff_id'],payload['digest'],require_fresh=False)
        if r['loaded']:
            return self.node.navigation_runtime.snapshot()
        self.odom()
        runtime=self.node.navigation_runtime
        with self.lock:
            self.receipt.update(phase='loading',loading=True,map_id=payload['map_id'])
        result=runtime.load({'map_id':payload['map_id'],'snapshot':r['snapshot'],'digest':r['digest'],
                             'control_session_id':r['snapshot']['session_id']})
        with self.lock:
            self.receipt.update(loaded=True,loading=False,phase='loaded',map_id=payload['map_id'])
        self.check(payload['handoff_id'],payload['digest'],require_fresh=False)
        return result

    def seed(self, payload):
        with self.operation:
            return self._seed(payload)

    def _seed(self, payload):
        r=self.check(payload['handoff_id'],require_unused=True)
        runtime=self.node.navigation_runtime
        if runtime.snapshot()['digest']!=r['digest']:
            raise RuntimeError('当前导航地图不是交接地图')
        if not r['loaded']:
            raise RuntimeError('交接地图尚未加载')
        # Consume before publishing: an ambiguous publication must never be retried.
        with self.lock:self.receipt.update(used=True,phase='seeding',seed_outcome='unknown')
        result=runtime.seed({**{k:r['pose'][k] for k in ['x','y','yaw']},'asset_digest':r['digest']})
        with self.lock:self.receipt.update(phase='localizing',seed_outcome='published')
        return result

    def status(self, payload):
        ident=payload.get('handoff_id')
        if not ident:
            info=self.diagnostic(payload)
            if not info.get('valid'):raise HandoffError('receipt_invalid','自动位姿记录已失效，请手动定位')
            ident=info['handoff_id']
        r=self.check(ident,require_fresh=False)
        runtime=self.node.navigation_runtime.snapshot()
        if r['loaded'] and runtime['digest']!=r['digest']:
            raise RuntimeError('导航地图已切换')
        grid=self.node.map_snapshot.snapshot()
        try:
            self.odom()
            odom_fresh=True
        except RuntimeError:
            odom_fresh=False
        if odom_fresh and runtime.get('localized') is True and runtime.get('state')=='ready':
            with self.lock:self.receipt['phase']='ready'
        ready=(odom_fresh and grid is not None and grid.get('asset_digest')==r['digest']
               and self.node.initial_pose_pub.get_subscription_count()>0)
        return {**runtime,'localized':runtime.get('localized',False) and odom_fresh,
                'automatic_pose_sent':r['used'],'initial_pose_ready':ready,
                'handoff':self.diagnostic({'handoff_id':ident})}

    def cancel(self, payload):
        # Serialize cancellation with publication and process startup: no late
        # load may bring Nav2 back after a cancellation has already returned.
        with self.operation:
            return self._cancel(payload)

    def _cancel(self, payload):
        with self.lock:
            r=self.receipt
            if not r or r['request_id']!=payload['request_id']: return {'cancelled':False}
            self.invalidate('user_or_host_cancelled')
            digest=r.get('digest');loaded=r.get('loaded') or r.get('loading')
        self.node.set_command('stop');self.node.set_mode('stop')
        if loaded and self.node.navigation_runtime.snapshot()['digest']==digest:
            self.node.navigation_runtime.stop()
        return {'cancelled':True}
