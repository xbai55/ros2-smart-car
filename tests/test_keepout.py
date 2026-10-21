import copy
import hashlib
import json
from types import SimpleNamespace as NS

import pytest
from smart_car_decision.keepout import inflate_keepout, validate_keepout
from smart_car_decision.navigation_config import validate_map_goal
from smart_car_decision.navigation_runtime import NavigationRuntime, validate_asset


def snapshot():return {'info':{'width':30,'height':30,'resolution':.1,'origin':{'x':0,'y':0,'yaw':0}},'data':[0]*900,'keepout':[0]*900,'header':{'frame_id':'map'},'session_id':'keepout-test'}


def test_inflation_matches_brute_force_and_never_edits_raw():
    for w,h,span in [(9,7,1),(2,3,4),(8,8,0)]:
        mask=[100 if i%13==0 else 0 for i in range(w*h)];before=mask[:]
        actual=inflate_keepout(mask,w,h,1,span)
        expected=[100 if any(mask[yy*w+xx] for yy in range(max(0,y-span),min(h,y+span+1)) for xx in range(max(0,x-span),min(w,x+span+1))) else 0 for y in range(h) for x in range(w)]
        assert actual==expected and mask==before


def test_keepout_blocks_goal_with_body_envelope_but_not_localization_map():
    grid=snapshot();grid['keepout'][15*30+15]=100;before=copy.deepcopy(grid)
    with pytest.raises(ValueError,match='禁行'):validate_map_goal({'x':1.35,'y':1.35},grid,.25)
    assert validate_map_goal({'x':.65,'y':.65},grid,.25)
    assert grid==before and not any(grid['data'])


def test_invalid_mask_and_unsupported_feature_fail_closed():
    grid=snapshot();grid['keepout']=[0]
    with pytest.raises(ValueError):validate_keepout(grid)
    grid=snapshot();grid['map_features']=['unknown-v2']
    with pytest.raises(ValueError):validate_keepout(grid)


def test_mask_changes_digest_and_unconfirmed_mask_blocks_navigation(tmp_path):
    grid=snapshot();raw=json.dumps(grid,ensure_ascii=False,allow_nan=False,separators=(',',':')).encode()
    payload={'snapshot':grid,'digest':hashlib.sha256(raw).hexdigest()}
    assert validate_asset(payload)
    payload['snapshot']['keepout'][0]=100
    with pytest.raises(ValueError,match='版本'):validate_asset(payload)
    runtime=NavigationRuntime(NS(),tmp_path);runtime.expected_keepout=grid
    assert '禁行' in runtime.health_error()
    assert 'keepout-v1' in runtime.snapshot()['map_features']


def test_ready_requires_both_matching_mask_and_filter_info(tmp_path):
    grid=snapshot();grid['keepout'][15*30+15]=100
    runtime=NavigationRuntime(NS(),tmp_path);runtime.expected_keepout={**grid,'data':list(grid['keepout'])}
    msg=NS(header=NS(frame_id='map'),info=NS(width=30,height=30,resolution=.1,origin=NS(position=NS(x=0,y=0),orientation=NS(z=0,w=1))),data=list(grid['keepout']))
    runtime.observe_keepout(msg)
    assert not runtime.snapshot()['keepout_ready']
    runtime.observe_keepout_info(NS(type=0,filter_mask_topic='/navigation/keepout_mask',base=0,multiplier=1))
    assert runtime.snapshot()['keepout_ready']
    msg.data[0]=100;runtime.observe_keepout(msg)
    assert not runtime.snapshot()['keepout_ready']
