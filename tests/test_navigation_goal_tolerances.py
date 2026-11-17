"""Final merged launch parameters and the Humble RotateToGoal latch boundary."""
import ast
import copy
import math
import tempfile
from pathlib import Path
from types import SimpleNamespace as NS

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
LAUNCH = ROOT/'ros2_ws/src/smart_car_decision/launch/navigation.launch.py'
OVERRIDES = ROOT/'ros2_ws/src/smart_car_decision/config/navigation.yaml'


def functions():
    tree = ast.parse(LAUNCH.read_text(encoding='utf-8'))
    names = {'merge_parameters','validate_goal_tolerances','launch_navigation'}
    ns = {'math':math,'Path':Path,'yaml':yaml,'tempfile':tempfile}
    exec(compile(ast.Module(body=[n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name in names],type_ignores=[]),str(LAUNCH),'exec'),ns)
    return ns


def humble_defaults():
    # Relevant namespaces from the installed Humble nav2_params.yaml. The full
    # on-device input and its merged output are also checked as audit artifacts.
    return {'controller_server':{'ros__parameters':{
        'controller_plugins':['FollowPath'],'goal_checker_plugins':['general_goal_checker'],
        'general_goal_checker':{'plugin':'nav2_controller::SimpleGoalChecker','stateful':True,'xy_goal_tolerance':.25,'yaw_goal_tolerance':.25},
        'FollowPath':{'plugin':'dwb_core::DWBLocalPlanner','xy_goal_tolerance':.25,
                      'critics':['RotateToGoal','Oscillation','BaseObstacle','GoalDist'],
                      'RotateToGoal.slowing_factor':5.,'RotateToGoal.lookahead_time':-1.}}},
        'map_server':{'ros__parameters':{'yaml_filename':''}}}


def merged():
    ns=functions()
    return ns['merge_parameters'](humble_defaults(),yaml.safe_load(OVERRIDES.read_text(encoding='utf-8')))


def test_merge_overrides_both_independent_goal_windows_without_relaxing_arrival():
    p=merged();functions()['validate_goal_tolerances'](p)
    c=p['controller_server']['ros__parameters']
    assert c['FollowPath']['xy_goal_tolerance']==.12
    assert c['general_goal_checker']['xy_goal_tolerance']==.15
    assert c['general_goal_checker']['yaw_goal_tolerance']==.20
    assert c['FollowPath']['critics'][0]=='RotateToGoal'
    assert c['FollowPath']['RotateToGoal.slowing_factor']==5.
    assert c['progress_checker']=={'required_movement_radius':.10,'movement_time_allowance':20.}


@pytest.mark.parametrize('window',[.25,float('nan'),float('inf'),0.,True])
def test_conflicting_or_invalid_final_window_refuses_launch(window):
    p=merged();p['controller_server']['ros__parameters']['FollowPath']['xy_goal_tolerance']=window
    with pytest.raises(RuntimeError):functions()['validate_goal_tolerances'](p)


def test_observed_stop_is_outside_arrival_but_inside_old_rotate_window():
    # Retry sample 50: errors calculated from map pose and the actual goal,
    # independently of the path-length feedback. Model upstream prepare() only.
    xy_error=.15624809355904043; yaw_error=.0009999999999998899;speed=2.2522206885358007e-7
    def rotation_latched(window):return xy_error**2<=window**2 and speed**2<=.03**2
    assert rotation_latched(.25)
    assert not (xy_error<=.15 and yaw_error<=.20)
    assert not rotation_latched(merged()['controller_server']['ros__parameters']['FollowPath']['xy_goal_tolerance'])


def test_launch_passes_checked_merged_yaml_to_every_nav2_process(tmp_path):
    from smart_car_decision.vehicle_geometry import FOOTPRINT, BOUNDING_RADIUS_M
    nav=tmp_path/'nav2';(nav/'params').mkdir(parents=True)
    (nav/'params/nav2_params.yaml').write_text(yaml.safe_dump(humble_defaults()),encoding='utf-8')
    share=tmp_path/'car';(share/'config').mkdir(parents=True)
    (share/'config/navigation.yaml').write_bytes(OVERRIDES.read_bytes())
    grid=tmp_path/'map.yaml';grid.write_text('image: map.pgm')
    args={'map':str(grid),'robot_radius':str(BOUNDING_RADIUS_M),'keepout':''}
    cleanup=[];ns=functions()
    ns.update(get_package_share_directory=lambda name:str(nav if name=='nav2_bringup' else share),
              LaunchConfiguration=lambda name:NS(perform=lambda _:args[name]),
              BOUNDING_RADIUS_M=BOUNDING_RADIUS_M,FOOTPRINT=FOOTPRINT,
              json=__import__('json'),atexit=NS(register=cleanup.append),
              IncludeLaunchDescription=lambda *a,**k:NS(**k),PythonLaunchDescriptionSource=lambda *a:NS(),
              Node=lambda **k:NS(**k))
    try:
        nodes=ns['launch_navigation'](None)
        controller=next(n for n in nodes if getattr(n,'package',None)=='nav2_controller')
        p=yaml.safe_load(Path(controller.parameters[0]).read_text())
        ns['validate_goal_tolerances'](p)
        assert p['controller_server']['ros__parameters']['FollowPath']['xy_goal_tolerance']==.12
        for scope in ('local','global'):
            c=p[f'{scope}_costmap'][f'{scope}_costmap']['ros__parameters']
            assert __import__('json').loads(c['footprint'])==FOOTPRINT
            assert c['footprint_padding']==0. and c['robot_radius']==BOUNDING_RADIUS_M
        assert p['velocity_smoother']['ros__parameters']['velocity_timeout']==.3
    finally:
        for f in cleanup:f()
