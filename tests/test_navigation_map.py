import math

import pytest

from smart_car_decision.navigation_config import fit_calibration, map_key, transform_point, validate_map_goal
from smart_car_decision.navigation_map import registered_obstacle_map
from test_navigation_config import anchors, lab_map, uploaded_anchors, uploaded_drawing


def value_at(snapshot, goal):
    info = snapshot["info"]
    origin = info["origin"]
    dx, dy = goal["x"] - origin["x"], goal["y"] - origin["y"]
    c, s = math.cos(origin["yaw"]), math.sin(origin["yaw"])
    x = math.floor((c * dx + s * dy) / info["resolution"])
    y = math.floor((-s * dx + c * dy) / info["resolution"])
    return snapshot["data"][y * info["width"] + x]


def test_solid_benches_block_navigation_even_when_lidar_map_is_empty():
    source = lab_map()
    source["data"][0] = -1
    calibration = fit_calibration(anchors(), source)
    snapshot = registered_obstacle_map(source, calibration)
    for drawing in ({"x": 400, "y": 165}, {"x": 900, "y": 398}, {"x": 912, "y": 120}):
        goal = transform_point(drawing, calibration["matrix"])
        assert value_at(snapshot, goal) == 100
        with pytest.raises(ValueError):
            validate_map_goal(goal, snapshot)
    for drawing in ({"x": 1015, "y": 180}, {"x": 1078, "y": 510}):
        validate_map_goal(transform_point(drawing, calibration["matrix"]), snapshot)
    assert snapshot["data"][0] == -1
    assert source["data"][4000] == 0
    assert value_at(source, transform_point({"x": 400, "y": 165}, calibration["matrix"])) == 0


def test_registration_required_before_obstacle_map_can_be_used():
    source = lab_map()
    assert set(registered_obstacle_map(source, None)["data"]) == {100}
    calibration = fit_calibration(anchors(), source)
    calibration["map_key"] = "old"
    assert set(registered_obstacle_map(source, calibration)["data"]) == {100}


def test_rotated_occupancy_origin_and_registration_mask():
    source = lab_map()
    source["info"]["origin"] = {"x": 13., "y": -1., "yaw": math.pi / 2}
    source["info"]["width"], source["info"]["height"] = 160, 300
    calibration = fit_calibration(anchors(), source)
    assert calibration["map_key"] == map_key(source)
    snapshot = registered_obstacle_map(source, calibration)
    goal = transform_point({"x": 400, "y": 165}, calibration["matrix"])
    assert value_at(snapshot, goal) == 100
    validate_map_goal(transform_point({"x": 1015, "y": 180}, calibration["matrix"]), snapshot)


def test_uploaded_visual_reference_never_injects_laboratory_obstacles():
    source = lab_map()
    source["data"][0] = -1
    source["data"][2000] = 100
    calibration = fit_calibration(uploaded_anchors(), source, uploaded_drawing())
    snapshot = registered_obstacle_map(source, calibration)
    assert snapshot["data"] == source["data"]
    assert snapshot["data"] is not source["data"]
    calibration["map_key"] = "obsolete"
    assert set(registered_obstacle_map(source, calibration)["data"]) == {100}


def test_navigation_map_cache_changes_when_drawing_identity_changes():
    from smart_car_decision.navigation_map import NavigationMapStore
    source = lab_map()
    calibration = fit_calibration(anchors(), source)
    store = NavigationMapStore()
    assert store.update(source, calibration)
    assert 100 in store.snapshot()["data"]
    calibration["drawing"] = uploaded_drawing(width=1208, height=552)
    assert store.update(source, calibration)
    assert store.snapshot()["data"] == source["data"]


def test_restarting_same_geometry_map_blocks_registered_navigation_map():
    from smart_car_decision.navigation_map import NavigationMapStore
    source = lab_map()
    calibration = fit_calibration(uploaded_anchors(), source, uploaded_drawing())
    store = NavigationMapStore()
    assert store.update(source, calibration)
    assert store.snapshot()["data"] == source["data"]
    calibration["invalidated"] = True
    assert store.update(source, calibration)
    assert set(store.snapshot()["data"]) == {100}
