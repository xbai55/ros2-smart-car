import math
import json
from pathlib import Path
from types import SimpleNamespace as N
from smart_car_decision.footprint import Rectangle
from smart_car_decision.avoidance import AvoidanceController,ScanEvidence,ZERO
from test_avoidance import scene,step

def detour_controller(*args, **kwargs):
    # These tests exercise the explicitly enabled planner, not product defaults.
    value = AvoidanceController(*args, **kwargs)
    value.settings['enabled'] = True
    return value



def test_live_recorded_gap_is_still_unknown_not_synthetic_obstacle():
    d=json.loads((Path(__file__).parent/'fixtures/measured-scan-20261028.json').read_text(encoding='utf-8'))
    cfg=d['calibration']; f=Rectangle(**cfg['rectangle'])
    s=N(**{k:d[k] for k in ('angle_min','angle_increment','range_min','range_max')},
        ranges=[float(v) for v in d['ranges']],header=N(stamp=N(**d['stamp'])))
    e=ScanEvidence(s,d['transform'],cfg['self_returns'],f,.01)
    c=detour_controller();c.footprint=f;c.settings['trigger_distance_m']=.4
    result=c.step({**ZERO,'linear_x':.1},mode='manual',now=0,evidence=e,scan_age=.1,pose=(0,0,0),odom_age=.1)
    assert result==ZERO
    assert c.coverage['kind']=='unknown'


def test_measured_geometry_keeps_existing_scan_origin():
    f=Rectangle(.0935,.2065,.1)
    assert math.isclose(f.front+f.rear,.30)
    assert math.isclose(f.front-.0435,.05)
    assert f.radius<=.25
    assert f.clearance((.0015,.3938))>.15
    assert f.clearance((.0015,.20))<.15


def test_rectangle_allows_side_space_but_turn_checks_rear_bag():
    f=Rectangle(.0935,.2065,.1)
    e=scene(obstacles=((0,.394,.01),))
    assert f.check(e,(.02,0,0),.15,(1,0)) is None
    assert f.check(scene(obstacles=((- .30,0,.02),)),(0,0,.1),.15)['kind']=='obstacle'
    c=detour_controller();c.footprint=f
    assert step(c,e)['linear_x']>0


def test_rectangle_unknown_rays_do_not_become_free():
    f=Rectangle(.0935,.2065,.1);e=scene(obstacles=())
    e.rays=[None]*len(e.rays)
    assert f.check(e,(.02,0,0),.15,(1,0))['kind']=='unknown'


def test_translation_hull_checks_obstacles_between_start_and_finish():
    f=Rectangle(.0935,.2065,.1)
    e=scene(obstacles=((.3,0,.01),))
    hull=f.translated_hull(.8,0)
    assert hull.check(e,(0,0,0),.15,(1,0),reference=f)['kind']=='obstacle'


def test_parallel_side_clearance_is_not_approaching_but_rotation_checks_it():
    f=Rectangle(.0935,.2065,.1)
    e=scene(obstacles=((- .04,-.12,.005),))
    assert f.check(e,(.02,0,0),.15,(1,0)) is None
    assert f.check(e,(0,0,.1),.15)['kind']=='obstacle'


def test_calibrated_echo_only_inside_body_and_still_occludes():
    f=Rectangle(.0935,.2065,.1)
    s=N(angle_min=math.pi,angle_increment=.01,range_min=.01,range_max=10,
        ranges=[.055],header=N(stamp=N(sec=1,nanosec=0)))
    e=ScanEvidence(s,self_returns=[(-.055,0)],footprint=f)
    assert not e.points and e.rays==[None] and e.self_return_count==1
    s.ranges=[.30]
    e=ScanEvidence(s,self_returns=[(-.055,0)],footprint=f)
    assert e.points and e.self_return_count==0


def test_small_angular_gap_has_limited_visibility_not_unlimited_free_space():
    s=N(angle_min=-math.pi,angle_increment=math.tau/1080,range_min=.01,range_max=10,
        ranges=[3.]*1080,header=N(stamp=N(sec=1,nanosec=0)))
    s.ranges[540]=float('inf')
    e=ScanEvidence(s,gap_width_m=.01)
    assert e.rays[540] is None and e.observed(.2,0)
    assert not e.observed(1.,0)
    s.ranges[540]=float('nan')
    assert not ScanEvidence(s,gap_width_m=.01).observed(.2,0)
    s.ranges[535:546]=[float('inf')]*11
    assert not ScanEvidence(s,gap_width_m=.01).observed(.2,0)
