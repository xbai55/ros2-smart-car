import asyncio
from types import SimpleNamespace as N, ModuleType
import sys
import pytest
from test_avoidance_adapter import controller
from test_navigation_start_wait import navigation, advance
from test_avoidance import scene
from smart_car_decision.nav2_obstacles import Nav2Obstacles

@pytest.mark.parametrize('enabled',[False,True])
def test_obstacle_stop_recovers_without_losing_navigation(controller,monkeypatch,enabled):
    c=controller;lease=navigation(c);owner=lease.owner
    c.avoidance.settings['enabled']=enabled
    c.scan_evidence=scene(obstacles=((.15,0,.02),))
    c.on_navigation_command(N(linear=N(x=.08,y=0.),angular=N(z=0.)))
    assert advance(c,monkeypatch,100.01)==(0,0,0)
    assert lease.owner==owner and c.interruption_reason in ('avoidance_blocked','avoidance_braking')
    c.scan_evidence=scene(obstacles=())
    c.on_navigation_command(N(linear=N(x=.08,y=0.),angular=N(z=.04)))
    assert advance(c,monkeypatch,100.02)[0]>0
    assert lease.owner==owner and c.interruption_reason is None


def test_persistent_obstacle_eventually_terminates(controller,monkeypatch):
    c=controller;lease=navigation(c);c.scan_evidence=scene(obstacles=((.15,0,.02),))
    c.on_navigation_command(N(linear=N(x=.08,y=0.),angular=N(z=0.)))
    advance(c,monkeypatch,100.01)
    c.on_navigation_command(N(linear=N(x=0.,y=0.),angular=N(z=0.)))
    advance(c,monkeypatch,120.02)
    assert lease.owner is None and c.interruption_reason=='navigation_obstacle_timeout'

@pytest.mark.parametrize('fault',['scan','lease','command','emergency'])
def test_navigation_safety_still_stops(controller,monkeypatch,fault):
    c=controller;lease=navigation(c)
    c.on_navigation_command(N(linear=N(x=.08,y=0.),angular=N(z=0.)))
    assert advance(c,monkeypatch,100.01)[0]>0
    if fault=='scan':c.evidence_at=c.last_scan_time=0.
    if fault=='lease':lease.deadline=0.
    if fault=='command':c.last_navigation_time=0.
    if fault=='emergency':c.on_emergency_stop(N(data=True))
    c.control_loop()
    assert c.output[-1].linear.x==0 and lease.owner is None


def test_switch_applies_both_nav2_layers_and_clears_old_costs(monkeypatch):
    def mod(name,**kw):
        m=ModuleType(name);m.__dict__.update(kw);monkeypatch.setitem(sys.modules,name,m)
    mod('rcl_interfaces.srv',SetParameters=N(Request=N))
    mod('rcl_interfaces.msg',Parameter=N,ParameterValue=N,ParameterType=N(PARAMETER_BOOL=1))
    mod('nav2_msgs.srv',ClearEntireCostmap=N(Request=N))
    calls=[];destroyed=[]
    def client(service,name):
        def call(request):calls.append((name,request));return N(results=[N(successful=True)])
        return N(service_is_ready=lambda:True,call_async=call)
    config=Nav2Obstacles(N(create_client=client,destroy_client=destroyed.append))
    async def wait(result):return result
    async def run():
        await config.apply(False,wait)
        assert config.applied is False
        await config.apply(True,wait)
        assert config.applied is True
        await config.apply(True,wait)
    asyncio.run(run())
    assert len(calls)==8 and len(destroyed)==8
    assert [r.parameters[0].value.bool_value for n,r in calls if n.endswith('set_parameters')]==[False,False,True,True]


def test_partial_nav2_failure_cannot_claim_applied(monkeypatch):
    config=Nav2Obstacles(N());calls=[]
    async def call(*args,**kwargs):
        calls.append(args[1])
        if len(calls)==3:raise RuntimeError('global unavailable')
    monkeypatch.setattr(config,'_call',call)
    # apply imports ROS request types; these are deliberately substituted.
    for name,values in [('rcl_interfaces.srv',dict(SetParameters=N(Request=N))),('rcl_interfaces.msg',dict(Parameter=N,ParameterValue=N,ParameterType=N(PARAMETER_BOOL=1))),('nav2_msgs.srv',dict(ClearEntireCostmap=N(Request=N)))]:
        m=ModuleType(name);m.__dict__.update(values);monkeypatch.setitem(sys.modules,name,m)
    with pytest.raises(RuntimeError):asyncio.run(config.apply(True,None))
    assert config.applied is None

@pytest.mark.parametrize('enabled',[False,True])
def test_kinematic_route_reaches_goal_with_measured_collision_guard(enabled):
    """Supplied path simulation; this does not substitute for DWB/Gazebo."""
    import math
    from smart_car_decision.avoidance import AvoidanceController
    from smart_car_decision.footprint import Rectangle
    from smart_car_decision.local_collision_guard import local_guard
    a=AvoidanceController();a.footprint=Rectangle(.0935,.1565,.1)
    pose=[0.,0.,0.];path=[(1.,0.)] if not enabled else [(0.,.5),(1.,.5),(1.,0.)]
    obstacles=() if not enabled else ((.5,0.,.10),)
    for goal in path:
        for _ in range(900):
            dx,dy=goal[0]-pose[0],goal[1]-pose[1]
            if math.hypot(dx,dy)<.025:break
            error=(math.atan2(dy,dx)-pose[2]+math.pi)%(2*math.pi)-math.pi
            motion={'linear_x':.10 if abs(error)<.10 else 0.,'linear_y':0.,'angular_z':max(-.3,min(.3,error))}
            result=local_guard(a,motion,evidence=scene(pose=pose,obstacles=obstacles),scan_age=.1,
                               speed=motion['linear_x'],angular=motion['angular_z'],velocity_age=.1,navigation=True)
            assert any(result.values()),a.reason
            pose[0]+=result['linear_x']*math.cos(pose[2])*.05
            pose[1]+=result['linear_x']*math.sin(pose[2])*.05
            pose[2]+=result['angular_z']*.05
        else:pytest.fail('Kinematic goal not reached')
    assert math.hypot(pose[0]-1.,pose[1])<.04


def test_navigation_does_not_double_expand_future_rotation():
    from smart_car_decision.avoidance import AvoidanceController
    from smart_car_decision.footprint import Rectangle
    from smart_car_decision.local_collision_guard import local_guard
    a=AvoidanceController();a.footprint=Rectangle(.0935,.1565,.1)
    evidence=scene(obstacles=((-.135,.205,.001),))
    args=dict(evidence=evidence,scan_age=.1,speed=0.,angular=0.,velocity_age=.1)
    motion={'linear_x':0.,'linear_y':0.,'angular_z':.6}
    assert not any(local_guard(a,motion,**args).values())
    assert local_guard(a,motion,navigation=True,**args)['angular_z']>0
