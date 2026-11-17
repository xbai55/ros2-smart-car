import copy
import time
from types import SimpleNamespace as NS

import pytest
from smart_car_decision.map_handoff import MapHandoff


@pytest.fixture
def handoff():
    now = [10.]
    grid = {'session_id':'mapping', 'updated_at':time.time(), 'data':[0]}
    state = {'state':'starting','digest':None}
    seeds = []
    node = NS(relative_odom={'x':0.,'y':0.,'yaw':0.,'stamp':1.,'frame_id':'odom','received_at':10.,'source_age_sec':0.},
              map_snapshot=NS(session_id='mapping',snapshot=lambda:copy.deepcopy(grid)),
              initial_pose_pub=NS(get_subscription_count=lambda:1))
    def load(p):
        state['digest']=p['digest'];grid['asset_digest']=p['digest'];return state.copy()
    node.navigation_runtime=NS(snapshot=lambda:state.copy(),load=load,seed=lambda p:seeds.append(p),stop=lambda:state.update(state='idle'))
    value=MapHandoff(node,clock=lambda:now[0])
    value.receipt={'request_id':'request','handoff_id':'handoff','snapshot':copy.deepcopy(grid),'digest':'digest',
                   'pose':{'x':1.,'y':2.,'yaw':.3},'odom':node.relative_odom.copy(),'at':10.,
                   'loaded':False,'used':False,'cancelled':False}
    return value,node,now,seeds


def test_only_exact_map_is_loaded_and_initial_pose_is_sent_once(handoff):
    h,n,_,seeds=handoff
    with pytest.raises(RuntimeError,match='地图已变化'):
        h.load({'handoff_id':'handoff','digest':'other','map_id':'map'})
    h.load({'handoff_id':'handoff','digest':'digest','map_id':'map'})
    assert h.status({'handoff_id':'handoff'})['initial_pose_ready']
    h.seed({'handoff_id':'handoff'})
    assert seeds==[{'x':1.,'y':2.,'yaw':.3,'asset_digest':'digest'}]
    with pytest.raises(RuntimeError,match='不重复'):
        h.seed({'handoff_id':'handoff'})


def test_pose_expires_and_restart_loses_authority(handoff):
    h,n,now,_=handoff
    now[0]+=301
    n.relative_odom['received_at']=now[0]
    with pytest.raises(RuntimeError,match='过期'):
        h.check('handoff')
    with pytest.raises(RuntimeError,match='失效'):
        MapHandoff(n).check('handoff')


def test_movement_out_and_back_permanently_invalidates_pose(handoff):
    h,n,_,_=handoff
    h.observe_odom({**n.relative_odom,'x':.06,'stamp':2.})
    h.observe_odom({**n.relative_odom,'x':0.,'stamp':3.})
    with pytest.raises(RuntimeError,match='失效'):
        h.check('handoff')


def test_odom_clock_reset_and_stale_data_rejected(handoff):
    h,n,now,_=handoff
    h.observe_odom({**n.relative_odom,'stamp':0.})
    with pytest.raises(RuntimeError): h.check('handoff')
    h.receipt['cancelled']=False
    now[0]+=.6
    with pytest.raises(RuntimeError,match='陈旧'): h.check('handoff')
    assert h.status({'handoff_id':'handoff'})['initial_pose_ready'] is False
    with pytest.raises(RuntimeError,match='陈旧'): h.seed({'handoff_id':'handoff'})


def test_other_mapping_session_rejected(handoff):
    h,n,_,_=handoff
    n.map_snapshot.session_id='different'
    with pytest.raises(RuntimeError,match='会话'): h.check('handoff')


def test_capture_keeps_mapping_lease_until_host_receives_snapshot():
    commands,modes=[],[]
    node=NS(relative_odom={'x':0.,'y':0.,'yaw':0.,'stamp':1.,'frame_id':'odom','source_age_sec':0.},
            set_command=commands.append,set_mode=modes.append,ros_status_age_sec=lambda:.01,
            mapping_restart=NS(snapshot=lambda:{'state':'ready'}),
            map_snapshot=NS(session_id='session',snapshot=lambda:{'session_id':'session','updated_at':time.time(),'data':[0]}),
            store=NS(snapshot=lambda:{'mode':'mapping','odom':{'ok':True,'odom_age_sec':.01,'linear_speed_xy':0.,'angular_speed':0.},
                                      'map_pose':{'ok':True,'updated_at':time.time(),'age_sec':.01,'x':0.,'y':0.,'yaw':0.}}))
    def validate(): node.relative_odom['received_at']=time.monotonic()
    h=MapHandoff(node)
    result=h.capture({'request_id':'request','session_id':'session'},validate)
    assert result['digest'] and result['snapshot']['session_id']=='session'
    assert commands==['stop'] and modes==[]
    assert h.capture({'request_id':'request','session_id':'session'},validate)==result


def test_capture_failure_releases_the_driving_guard(handoff):
    h,n,_,_=handoff
    n.mapping_restart=NS(snapshot=lambda:{'state':'ready'})
    n.set_command=lambda _:None
    n.set_mode=lambda _:None
    h.receipt=None
    with pytest.raises(RuntimeError):
        h.capture({'request_id':'request','session_id':'mapping'},lambda:(_ for _ in ()).throw(RuntimeError('lost lease')))
    assert not h.active()


@pytest.mark.parametrize('change,code',[({'x':.06},'position_changed'),({'yaw':.06},'heading_changed'),({'stamp':0.},'odom_stamp_backwards'),({'frame_id':'other'},'odom_frame_changed')])
def test_first_invalidation_reason_is_retained(handoff,change,code):
    h,n,_,_=handoff
    h.observe_odom({**n.relative_odom,**change})
    h.observe_odom({**n.relative_odom,'x':1.})
    first=h.diagnostic({'request_id':'request'})
    assert not first['valid'] and first['failure']['code']==code
    n.set_command=n.set_mode=lambda _:None
    h.cancel({'request_id':'request'})
    assert h.diagnostic({'request_id':'request'})['failure']==first['failure']


def test_internal_map_session_transition_and_idempotent_load(handoff):
    h,n,_,_=handoff;calls=[]
    def load(p):
        calls.append(p);n.map_snapshot.session_id='navigation'
        h.check('handoff',require_fresh=False)
        n.navigation_runtime.snapshot=lambda:{'state':'starting','digest':'digest'}
        return {'state':'starting','digest':'digest'}
    n.navigation_runtime.load=load
    h.load({'handoff_id':'handoff','digest':'digest','map_id':'map'})
    h.load({'handoff_id':'handoff','digest':'digest','map_id':'map'})
    assert len(calls)==1


def test_seed_unknown_outcome_is_not_published_twice(handoff):
    h,n,_,_=handoff
    h.load({'handoff_id':'handoff','digest':'digest','map_id':'map'})
    calls=[]
    def seed(p):calls.append(p);raise RuntimeError('publication interrupted')
    n.navigation_runtime.seed=seed
    with pytest.raises(RuntimeError):h.seed({'handoff_id':'handoff'})
    assert h.diagnostic({'request_id':'request'})['seed_outcome']=='unknown'
    with pytest.raises(RuntimeError):h.seed({'handoff_id':'handoff'})
    assert len(calls)==1


def test_completed_handoff_cannot_rearm_guard_when_localization_later_changes(handoff):
    h,n,_,_=handoff
    h.load({'handoff_id':'handoff','digest':'digest','map_id':'map'})
    h.seed({'handoff_id':'handoff'})
    state={'state':'ready','localized':True,'digest':'digest'}
    n.navigation_runtime.snapshot=lambda:state.copy()
    h.status({'handoff_id':'handoff'})
    state.update(state='localizing',localized=False)
    assert not h.active()
    h.observe_odom({**n.relative_odom,'x':2.})
    assert h.diagnostic({'request_id':'request'})['failure'] is None


@pytest.mark.parametrize('kind',['invalid','stale','nonfinite','odom_stale','session_change','cancel'])
def test_capture_waits_for_fresh_evidence_within_one_budget(monkeypatch,kind):
    import smart_car_decision.map_handoff as module
    now=[100.];commands=[];modes=[]
    monkeypatch.setattr(module.time,'monotonic',lambda:now[0])
    monkeypatch.setattr(module.time,'time',lambda:now[0])
    monkeypatch.setattr(module.time,'sleep',lambda delay:now.__setitem__(0,now[0]+delay))
    monkeypatch.setattr(module,'CAPTURE_WAIT',1.5)
    node=NS(relative_odom={'x':0.,'y':0.,'yaw':0.,'stamp':1.,'frame_id':'odom','source_age_sec':0.,'received_at':100.},
            set_command=commands.append,set_mode=modes.append,ros_status_age_sec=lambda:.01,
            mapping_restart=NS(snapshot=lambda:{'state':'ready'}))
    node.map_snapshot=NS(session_id='session',snapshot=lambda:{'session_id':'session','updated_at':now[0],'data':[0]})
    def snapshot():
        old=now[0]<100.9
        pose={'ok':not(old and kind=='invalid'),'updated_at':now[0]-(1 if old and kind=='stale' else 0),
              'age_sec':.01,'x':float('nan') if old and kind=='nonfinite' else 1.,'y':2.,'yaw':.1}
        return {'mode':'mapping','odom':{'ok':True,'odom_age_sec':.01,'linear_speed_xy':0.,'angular_speed':0.},'map_pose':pose}
    node.store=NS(snapshot=snapshot)
    h=MapHandoff(node,clock=lambda:now[0])
    def validate():
        node.relative_odom['received_at']=now[0]-(1 if kind=='odom_stale' and now[0]<100.4 else 0)
        if now[0]>=100.3 and kind=='session_change':node.map_snapshot.session_id='changed'
        if now[0]>=100.3 and kind=='cancel':h.receipt['cancelled']=True
    if kind in {'session_change','cancel'}:
        with pytest.raises(RuntimeError):h.capture({'request_id':'r','session_id':'session'},validate)
        assert modes==['stop'] and not h.active()
    else:
        result=h.capture({'request_id':'r','session_id':'session'},validate)
        assert now[0]>=100.9 and result['handoff_id'] and h.receipt['pose']['x']==1.
        assert commands==['stop'] and modes==[]


def test_capture_pose_failure_keeps_specific_timeout_reason(monkeypatch):
    import smart_car_decision.map_handoff as module
    now=[100.]
    monkeypatch.setattr(module.time,'time',lambda:now[0])
    monkeypatch.setattr(module.time,'sleep',lambda delay:now.__setitem__(0,now[0]+delay))
    monkeypatch.setattr(module,'CAPTURE_WAIT',1.)
    node=NS(relative_odom={'x':0.,'y':0.,'yaw':0.,'stamp':1.,'frame_id':'odom','source_age_sec':0.},
        set_command=lambda _:None,set_mode=lambda _:None,ros_status_age_sec=lambda:.01,
        mapping_restart=NS(snapshot=lambda:{'state':'ready'}),
        map_snapshot=NS(session_id='s',snapshot=lambda:{'session_id':'s','updated_at':now[0],'data':[0]}),
        store=NS(snapshot=lambda:{'odom':{'ok':True,'odom_age_sec':.01,'linear_speed_xy':0.,'angular_speed':0.},'map_pose':{'ok':False}}))
    h=MapHandoff(node,clock=lambda:now[0])
    with pytest.raises(module.HandoffError,match='新鲜地图位姿超时'):
        h.capture({'request_id':'r','session_id':'s'},lambda:node.relative_odom.update(received_at=now[0]))
    assert h.receipt['failure']['code']=='pose_not_ready' and not h.active()
