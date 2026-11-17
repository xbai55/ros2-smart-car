import json
import math
from pathlib import Path

import pytest
import yaml
from smart_car_decision.vehicle_geometry import BODY_LENGTH_M, BODY_WIDTH_M, BOUNDING_RADIUS_M, FOOTPRINT
from smart_car_decision.footprint import Rectangle


def test_navigation_body_matches_operator_dimensions_and_base_offset():
    assert BODY_LENGTH_M == pytest.approx(.25)
    assert BODY_WIDTH_M == pytest.approx(.20)
    assert max(p[0] for p in FOOTPRINT) == .0935
    assert min(p[0] for p in FOOTPRINT) == -.1565
    assert all(math.hypot(*p)<=BOUNDING_RADIUS_M+1e-12 for p in FOOTPRINT)
    path=Path(__file__).resolve().parents[1]/'ros2_ws/src/smart_car_decision/config/navigation.yaml'
    config=yaml.safe_load(path.read_text())
    for name in ['local_costmap','global_costmap']:
        params=config[name][name]['ros__parameters']
        assert json.loads(params['footprint'])==FOOTPRINT
        assert params['robot_radius']==BOUNDING_RADIUS_M


def test_smaller_body_does_not_filter_real_returns_outside_twenty_cm_width():
    body=Rectangle(.0935,.1565,.1)
    assert body.clearance((-.03,-.099))<0
    assert body.clearance((-.03,-.111))==pytest.approx(.011)
    # A nearby external hit must remain subject to the existing safety margin.
    from types import SimpleNamespace as NS
    hit=body.check(NS(points=[(-.03,-.111)],full=True),(0,0,0),.05)
    assert hit['kind']=='obstacle'
