import math

from smart_car_decision.avoidance import AvoidanceController,ZERO
from smart_car_decision.footprint import Rectangle
from test_avoidance import scene,step

def detour_controller(*args, **kwargs):
    # These tests exercise the explicitly enabled planner, not product defaults.
    value = AvoidanceController(*args, **kwargs)
    value.settings['enabled'] = True
    return value



def controller():
    c=detour_controller(motion_model='holonomic')
    c.footprint=Rectangle(.0935,.1565,.105)
    c.settings['trigger_distance_m']=.4
    return c


def test_touching_rear_wall_can_depart_but_not_reverse_or_rotate():
    c=controller();e=scene(obstacles=())
    e.points=[(-.1565,0.)]
    assert step(c,e)['linear_x']>0
    c.actual_speed,c.scan_age=0.,.05
    assert c.guard({**ZERO,'linear_x':-.05},e,.30)==ZERO
    c.reset()
    assert c.guard({**ZERO,'angular_z':.1},e,.30)==ZERO


def test_physical_body_overlap_is_never_ignored_as_separating():
    c=controller();e=scene(obstacles=());e.points=[(-.15,0.)]
    assert step(c,e)==ZERO and c.coverage['kind']=='obstacle'


def test_lateral_departure_from_rear_wall_checks_approached_side():
    c=controller();e=scene(obstacles=());e.points=[(-.1565,0.)]
    c.actual_speed,c.scan_age=0.,.05
    assert c.guard({**ZERO,'linear_y':.05},e,.30)['linear_y']>0
    e.points.append((0.,.13))
    assert c.guard({**ZERO,'linear_y':.05},e,.30)==ZERO


def test_unknown_rear_does_not_block_forward_but_unknown_front_does():
    c=controller();e=scene(obstacles=())
    e.rays=[r if math.cos(e.start+i*e.increment)>=0 else None for i,r in enumerate(e.rays)]
    assert step(c,e)['linear_x']>0
    e.rays[360]=None
    assert step(c,e,now=.1)==ZERO and c.state=='waiting_observation'


def test_detour_uses_translation_with_near_rear_object_and_release_stops():
    c=controller();obstacles=((.55,0.,.08),(-.18,0.,.01))
    step(c,scene(obstacles=obstacles,sequence=1))
    step(c,scene(obstacles=obstacles,sequence=2),now=.15)
    assert c.path and c.direction=='left'
    assert abs(c.path[0][0])<1e-9
    result=step(c,scene(obstacles=obstacles,sequence=3),now=.2)
    assert result['linear_y']>0 and result['angular_z']==0 and result['linear_x']==0
    assert c.step(ZERO,mode='manual',now=.25,evidence=None,scan_age=2,pose=None,odom_age=2)==ZERO
    assert not c.path


def test_closed_loop_fixed_heading_detour_finishes_without_contact():
    c=controller();pose=[0.,0.,0.];obstacles=((.55,0.,.08),(-.18,0.,.01))
    started=False;max_y=0.
    for i in range(500):
        output=step(c,scene(tuple(pose),obstacles=obstacles,sequence=i//3),
                    now=i*.05,pose=tuple(pose))
        started=started or c.anchor is not None
        assert output['angular_z']==0 and output['linear_x']>=0
        pose[0]+=output['linear_x']*.05;pose[1]+=output['linear_y']*.05
        max_y=max(max_y,abs(pose[1]))
        for x,y,r in obstacles:
            assert c.footprint.clearance((x,y),tuple(pose))>r
        assert c.state not in {'blocked','timeout','sensor_fault'}
        if started and c.anchor is None:break
    assert started and c.anchor is None and pose[0]>.55 and max_y>.20


def test_navigation_keeps_nav2_direction_including_angular_command():
    c=controller();motion={**ZERO,'linear_x':.04,'angular_z':.08}
    result=c.step(motion,mode='navigation',now=0,evidence=scene(obstacles=()),
                  scan_age=.05,pose=(0,0,0),odom_age=.05)
    assert result==motion and not c.path


def test_short_lateral_lane_is_found_when_25cm_offset_hits_side_wall():
    c=controller();e=scene(obstacles=())
    e.points=[(.5,0.),(.55,.4),(.8,.4),(0.,.55),(-.05,-.2)]
    assert c.choose_translation(e,(0.,0.,0.),c.radius+.05)
    assert c.direction=='left' and c.path[0]==(0.,.20)
    assert c.footprint.translated_hull(0.,.25).check(
        e,(0,0,0),.05,(0,1),reference=c.footprint) is None
    # The longer lateral leg itself is clear, but its forward continuation
    # approaches the side wall within 5 cm and must still be rejected.
    assert c.footprint.translated_hull(c.path[1][0],0).check(
        e,(0,.25,0),.05,(1,0),reference=c.footprint)['kind']=='obstacle'
