import math

import pytest
from fastapi.testclient import TestClient

from smart_car_decision.navigation_config import NavigationConfigStore, fit_calibration, map_key, transform_point, validate_map_goal
from smart_car_decision.web_api import create_app
from smart_car_decision.control_policy import decide_motion, zero_motion


def lab_map():
    return {"header": {"frame_id": "map"}, "info": {"width": 300, "height": 160, "resolution": .05,
            "origin": {"x": -1., "y": -1., "yaw": 0.}}, "data": [0] * 48000}


def anchors():
    return [{"drawing": {"x": x, "y": y}, "world": {"x": x * .01, "y": 5.52 - y * .01}}
            for x, y in ((0, 0), (1208, 0), (0, 552), (1208, 552))]


def test_four_point_registration_handles_y_flip_translation_and_persistence(tmp_path):
    path = tmp_path / "navigation.json"
    store = NavigationConfigStore(path)
    calibration = store.calibrate(anchors(), lab_map())["calibration"]
    goal = transform_point({"x": 1015, "y": 180}, calibration["matrix"])
    assert goal["x"] == pytest.approx(10.15)
    assert goal["y"] == pytest.approx(3.72)
    store.add_place({"name": "实验台旁", "drawing": {"x": 600, "y": 280}, "yaw": 0}, lab_map())
    restored = NavigationConfigStore(path).snapshot()
    assert restored["places"][-1]["name"] == "实验台旁"
    assert restored["calibration"] == calibration
    store.remove_place(restored["places"][-1]["id"])
    assert len(NavigationConfigStore(path).snapshot()["places"]) == 2


def test_registration_rejects_collinear_points_and_bad_fourth_observation():
    with pytest.raises(ValueError, match="同一直线"):
        fit_calibration([{ "drawing": {"x": x, "y": 40}, "world": {"x": x * .01, "y": 0}} for x in (0, 200, 600, 1000)], lab_map())
    pairs = anchors()
    pairs[-1]["world"]["x"] += 1
    with pytest.raises(ValueError, match="对齐误差"):
        fit_calibration(pairs, lab_map())


@pytest.mark.parametrize("cell", [-1, 30, 100])
def test_goal_requires_clear_vehicle_footprint(cell):
    snapshot = lab_map()
    snapshot["data"][60 * 300 + 44] = cell
    with pytest.raises(ValueError, match="安全边界"):
        validate_map_goal({"x": 1, "y": 2}, snapshot)


def test_goal_rejects_out_of_bounds_nan_and_rotated_map():
    snapshot = lab_map()
    with pytest.raises(ValueError):
        validate_map_goal({"x": math.nan, "y": 0}, snapshot)
    with pytest.raises(ValueError):
        validate_map_goal({"x": -1, "y": -1}, snapshot)
    snapshot["info"]["origin"]["yaw"] = math.pi / 2
    assert validate_map_goal({"x": -3, "y": 1}, snapshot) == {"x": -3., "y": 1.}


def test_place_rejects_bench_and_unregistered_map(tmp_path):
    store = NavigationConfigStore(tmp_path / "nav.json")
    with pytest.raises(ValueError, match="对齐"):
        store.add_place({"name": "点", "drawing": {"x": 400, "y": 280}}, None)
    store.calibrate(anchors(), lab_map())
    with pytest.raises(ValueError, match="空地"):
        store.add_place({"name": "台上", "drawing": {"x": 400, "y": 165}}, lab_map())


def navigation_motion(**overrides):
    params = dict(mode="navigation", emergency_stop=False, front_distance=3, detection="", manual_command="forward", lane_offset=0,
                  has_recent_detection=False, has_recent_manual=True, has_recent_lane=False,
                  navigation_motion={"linear_x": .3, "linear_y": .4, "angular_z": .8}, has_recent_navigation=True)
    params.update(overrides)
    return decide_motion(**params)


@pytest.mark.parametrize("override", [{"emergency_stop": True}, {"has_recent_navigation": False}, {"has_recent_scan": False}, {"front_distance": .2}, {"navigation_motion": {"linear_x": math.nan}}])
def test_navigation_is_arbitrated_and_stops_on_invalid_inputs(override):
    assert navigation_motion(**override) == zero_motion()


def test_navigation_speed_limit_preserves_direction():
    motion = navigation_motion(speed_scale=.5)
    assert math.hypot(motion["linear_x"], motion["linear_y"]) == pytest.approx(.09)
    assert motion["linear_x"] / motion["linear_y"] == pytest.approx(.75)
    assert motion["angular_z"] == pytest.approx(.144)


def test_navigation_api_config_calibration_and_unavailable_nav2(fake_node, tmp_path):
    fake_node.navigation_config = NavigationConfigStore(tmp_path / "nav.json")
    fake_node.map_snapshot.update(lab_map())
    client = TestClient(create_app(fake_node))
    assert client.get("/api/navigation/config").json()["places"][0]["name"] == "老师处"
    assert client.post("/api/navigation/calibration", json={"anchors": anchors(), "map_key": "old"}).status_code == 409
    assert client.post("/api/navigation/calibration", json={"anchors": anchors(), "map_key": map_key(lab_map())}).status_code == 200
    response = client.post("/api/navigation/places", json={"name": "实验台旁", "drawing": {"x": 600, "y": 280}, "yaw": 0})
    assert response.status_code == 200
    place_id = response.json()["places"][-1]["id"]
    assert client.delete(f"/api/navigation/places/{place_id}").status_code == 200
    assert client.post("/api/navigation/plan", json={}).status_code == 503
    assert client.get("/api/status").json()["navigation"]["ready"] is False
    assert client.post("/api/navigation/cancel", json={}).status_code == 200


def uploaded_drawing(**changes):
    return {"id": "map-123", "name": "上传平面图", "kind": "uploaded", "width": 2400,
            "height": 1200, "revision": "image-v1", **changes}


def uploaded_anchors():
    return [{"drawing": {"x": x, "y": y}, "world": {"x": x * .005, "y": 6-y*.005}}
            for x, y in ((0, 0), (2400, 0), (0, 1200), (2400, 1200))]


def test_uploaded_calibration_uses_image_bounds_and_resets_foreign_places(tmp_path):
    store = NavigationConfigStore(tmp_path / "navigation.json")
    store.calibrate(anchors(), lab_map())
    result = store.calibrate(uploaded_anchors(), lab_map(), uploaded_drawing())
    assert result["places"] == []
    calibration = result["calibration"]
    assert calibration["drawing"]["width"] == 2400
    assert calibration["rms_error"] < 1e-10
    assert len(calibration["errors"]) == 4
    assert transform_point({"x": 2000, "y": 900}, calibration["matrix"])["x"] == pytest.approx(10)
    store.add_place({"name": "上传图中的空地", "drawing": {"x": 2000, "y": 900}}, lab_map())
    store.calibrate(uploaded_anchors(), lab_map(), uploaded_drawing(name="地图重命名"))
    assert len(store.snapshot()["places"]) == 1
    assert NavigationConfigStore(store.path).snapshot()["calibration"]["drawing"]["name"] == "地图重命名"
    store.calibrate(uploaded_anchors(), lab_map(), uploaded_drawing(revision="image-v2"))
    assert store.snapshot()["places"] == []
    assert store.calibrate(anchors(), lab_map())["places"][0]["id"] == "teacher"


@pytest.mark.parametrize("changes", [{"width": 0}, {"height": True}, {"width": 1.5}, {"width": 16000001},
                                     {"kind": "unknown"}, {"id": ""}, {"name": ""}, {"revision": []}])
def test_invalid_uploaded_drawing_rejected(changes):
    with pytest.raises((ValueError, TypeError)):
        fit_calibration(uploaded_anchors(), lab_map(), uploaded_drawing(**changes))


def test_calibration_rejects_clustered_and_repeated_anchors():
    clustered = [{"drawing": {"x": x, "y": y}, "world": {"x": x*.01, "y": y*.01}}
                 for x, y in ((100, 100), (110, 100), (100, 110), (110, 110))]
    with pytest.raises(ValueError, match="集中"):
        fit_calibration(clustered, lab_map())
    repeated = anchors()
    repeated[-1] = repeated[0]
    with pytest.raises(ValueError, match="重复"):
        fit_calibration(repeated, lab_map())


def test_uploaded_places_still_require_measured_occupancy_clearance(tmp_path):
    store = NavigationConfigStore(tmp_path / "navigation.json")
    source = lab_map()
    store.calibrate(uploaded_anchors(), source, uploaded_drawing())
    goal = transform_point({"x": 2000, "y": 900}, store.snapshot()["calibration"]["matrix"])
    source["data"][50 * 300 + 220] = 100
    assert goal == pytest.approx({"x": 10, "y": 1.5})
    with pytest.raises(ValueError, match="安全边界"):
        store.add_place({"name": "障碍内", "drawing": {"x": 2000, "y": 900}}, source)
    with pytest.raises(ValueError, match="平面图"):
        store.add_place({"name": "图外", "drawing": {"x": 2400, "y": 900}}, source)


def test_uploaded_calibration_api_passes_descriptor(fake_node, tmp_path):
    fake_node.navigation_config = NavigationConfigStore(tmp_path / "nav.json")
    fake_node.map_snapshot.update(lab_map())
    client = TestClient(create_app(fake_node))
    response = client.post("/api/navigation/calibration", json={"anchors": uploaded_anchors(),
                            "map_key": map_key(lab_map()), "drawing": uploaded_drawing()})
    assert response.status_code == 200
    assert response.json()["calibration"]["drawing"]["id"] == "map-123"
    assert response.json()["places"] == []


@pytest.mark.parametrize("stale", ["map_key", "calibration_matrix", "calibration_drawing"])
def test_save_place_rejects_stale_caller_context(tmp_path, stale):
    store = NavigationConfigStore(tmp_path / "nav.json")
    source = lab_map()
    calibration = store.calibrate(uploaded_anchors(), source, uploaded_drawing())["calibration"]
    payload = {"name": "旧页面地点", "drawing": {"x": 2000, "y": 900}, "yaw": 0,
               "map_key": map_key(source), "calibration_matrix": calibration["matrix"],
               "calibration_drawing": calibration["drawing"]}
    if stale == "map_key":
        payload[stale] = "old-map"
    elif stale == "calibration_matrix":
        payload[stale] = [1, 0, 0, 0, 1, 0]
    else:
        # Identical matrix with a different image must still be rejected.
        store.calibrate(uploaded_anchors(), source, uploaded_drawing(id="another-image"))
    with pytest.raises(ValueError, match="变化"):
        store.add_place(payload, source)
    assert store.snapshot()["places"] == []
    assert NavigationConfigStore(store.path).snapshot()["places"] == []


def test_save_place_accepts_current_context_and_legacy_callers(tmp_path):
    store = NavigationConfigStore(tmp_path / "nav.json")
    source = lab_map()
    calibration = store.calibrate(uploaded_anchors(), source, uploaded_drawing())["calibration"]
    result = store.add_place({"name": "当前地点", "drawing": {"x": 2000, "y": 900},
               "map_key": map_key(source), "calibration_matrix": calibration["matrix"],
               "calibration_drawing": {**calibration["drawing"], "name": "重命名后的地图"}}, source)
    assert len(result["places"]) == 1
    result = store.add_place({"name": "兼容旧请求", "drawing": {"x": 1900, "y": 900}}, source)
    assert len(result["places"]) == 2


def test_save_place_api_rejects_changed_drawing_context(fake_node, tmp_path):
    fake_node.navigation_config = NavigationConfigStore(tmp_path / "nav.json")
    source = lab_map()
    fake_node.map_snapshot.update(source)
    store = fake_node.navigation_config
    old = store.calibrate(uploaded_anchors(), source, uploaded_drawing())["calibration"]
    store.calibrate(uploaded_anchors(), source, uploaded_drawing(id="new-image"))
    client = TestClient(create_app(fake_node))
    response = client.post("/api/navigation/places", json={"name": "旧页面点", "drawing": {"x": 2000, "y": 900},
                          "map_key": map_key(source), "calibration_matrix": old["matrix"], "calibration_drawing": old["drawing"]})
    assert response.status_code == 422
    assert "平面图已变化" in response.json()["detail"]
    assert store.snapshot()["places"] == []


def test_explicit_slam_restart_invalidates_registration_without_losing_pixel_places(fake_node, tmp_path):
    store = NavigationConfigStore(tmp_path / "nav.json")
    source = lab_map()
    original = store.calibrate(uploaded_anchors(), source, uploaded_drawing())["calibration"]
    store.add_place({"name": "保留的像素地点", "drawing": {"x": 2000, "y": 900}}, source)
    fake_node.navigation_config = store
    fake_node.map_snapshot.update(source)
    fake_node.store.update(lidar={"ok": True}, odom={"ok": True}, tf={"ok": True})
    refreshed = []
    fake_node.refresh_navigation_map = lambda: refreshed.append(store.snapshot()["calibration"]["invalidated"])
    client = TestClient(create_app(fake_node))
    assert client.post("/api/mapping/restart").status_code == 200
    invalid = NavigationConfigStore(store.path).snapshot()
    assert invalid["calibration"]["invalidated"] is True
    assert invalid["calibration"]["drawing"] == original["drawing"]
    assert invalid["calibration"]["map_key"] == map_key(source)
    assert len(invalid["places"]) == 1
    assert refreshed == [True]
    with pytest.raises(ValueError, match="对齐"):
        store.add_place({"name": "不能继续保存", "drawing": {"x": 1900, "y": 900}}, source)
    renewed = store.calibrate(uploaded_anchors(), source, uploaded_drawing())
    assert not renewed["calibration"].get("invalidated")
    assert len(renewed["places"]) == 1


def test_blocked_slam_restart_does_not_invalidate_registration(fake_node, tmp_path):
    store = NavigationConfigStore(tmp_path / "nav.json")
    store.calibrate(anchors(), lab_map())
    fake_node.navigation_config = store
    response = TestClient(create_app(fake_node)).post("/api/mapping/restart")
    assert response.status_code == 409
    assert not store.snapshot()["calibration"].get("invalidated")


def test_failed_slam_restart_cannot_restore_old_registration(fake_node, tmp_path):
    store = NavigationConfigStore(tmp_path / "nav.json")
    store.calibrate(anchors(), lab_map())
    fake_node.navigation_config = store
    fake_node.store.update(lidar={"ok": True}, odom={"ok": True}, tf={"ok": True})
    def fail_restart():
        raise RuntimeError("SLAM launch failed after stopping its old process")
    fake_node.mapping_restart.restart = fail_restart
    response = TestClient(create_app(fake_node)).post("/api/mapping/restart")
    assert response.status_code == 500
    assert NavigationConfigStore(store.path).snapshot()["calibration"]["invalidated"] is True
