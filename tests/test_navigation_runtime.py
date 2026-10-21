import hashlib
import json
import math
import time
from types import SimpleNamespace as NS

import pytest
import yaml

from smart_car_decision.map_assets import save_occupancy_snapshot, read_pgm
from smart_car_decision.mapping_session import MapSnapshotStore
from smart_car_decision.navigation_config import map_key
from smart_car_decision.navigation_runtime import NavigationRuntime, validate_asset
from test_mapping_session import grid


def asset():
    store = MapSnapshotStore()
    store.update(grid(data=[0, 50, -1, 100]))
    value = store.snapshot()
    raw = json.dumps(value, ensure_ascii=False, allow_nan=False, separators=(",", ":")).encode()
    return {"snapshot": value, "digest": hashlib.sha256(raw).hexdigest(), "map_id": "one"}


def test_saved_grid_reloads_unknown_and_intermediate_as_unknown(tmp_path):
    payload = asset()
    snapshot, digest = validate_asset(payload)
    files = save_occupancy_snapshot(snapshot, tmp_path, "map")
    config = yaml.safe_load(open(files["yaml_path"]))
    width, height, maximum, pixels = read_pgm(files["pgm_path"])
    image = [-1 if config["free_thresh"] <= (maximum - v) / maximum <= config["occupied_thresh"] else 0 if (maximum - v) / maximum < config["free_thresh"] else 100 for v in pixels]
    cells = sum([image[row * width:(row + 1) * width] for row in range(height - 1, -1, -1)], [])
    assert cells == [0, -1, -1, 100]
    store = MapSnapshotStore()
    store.expect_asset(snapshot, digest)
    assert store.update(grid(data=cells))
    assert store.snapshot()["asset_digest"] == digest
    msg = grid(data=cells)
    msg.header.frame_id = "wrong-map"
    assert not store.update(msg)


def test_same_geometry_different_session_does_not_reuse_calibration():
    value = asset()["snapshot"]
    assert map_key(value) != map_key({**value, "session_id": "new-session"})
    assert map_key({**value, "asset_digest": "same"}) == map_key({**value, "session_id": "new", "asset_digest": "same"})


def test_asset_digest_and_finite_geometry_checked():
    payload = asset()
    payload["snapshot"]["data"][0] = 100
    with pytest.raises(ValueError, match="版本"):
        validate_asset(payload)


def test_amcl_requires_new_nonzero_covariance_samples_and_expires(tmp_path):
    runtime = NavigationRuntime(NS(), tmp_path)
    runtime.state.update(digest="grid", initial_pose_at=time.time() - .1)
    def pose(stamp, covariance):
        return NS(header=NS(frame_id="map", stamp=NS(sec=int(stamp), nanosec=int(stamp % 1 * 1e9))),
                  pose=NS(covariance=covariance, pose=NS(position=NS(x=1., y=2.), orientation=NS(z=0., w=1.))))
    now = time.time()
    runtime.observe_pose(pose(now, [0.] * 36))
    assert not runtime.state["localized"]
    covariance = [.0] * 36
    for k in (0, 7, 35):
        covariance[k] = .01
    runtime.observe_pose(pose(now + .01, covariance))
    assert not runtime.state["localized"]
    runtime.observe_pose(pose(now + .02, covariance))
    assert runtime.state["localized"] and not runtime.health_error()
    runtime.state["pose_at"] -= 10
    assert "超时" in runtime.health_error()


def test_loading_requires_zero_planar_speed_not_only_longitudinal_speed(tmp_path):
    status = {"mode": "stop", "odom": {"ok": True, "linear_speed": 0., "linear_speed_xy": .2, "angular_speed": 0.}}
    node = NS(store=NS(snapshot=lambda: status), ros_status_age_sec=lambda: .1)
    runtime = NavigationRuntime(node, tmp_path)
    with pytest.raises(RuntimeError, match="停止"):
        runtime.stationary()
    status["odom"]["linear_speed_xy"] = 0
    runtime.stationary()


def test_stopped_localization_requires_stability_and_rejects_drift(tmp_path):
    mode = {"mode": "stop"}
    runtime = NavigationRuntime(NS(store=NS(snapshot=lambda: mode)), tmp_path)
    start = time.time()
    runtime.state.update(digest="grid", initial_pose_at=start - 1)
    covariance = [0.] * 36
    for k in (0, 7, 35):
        covariance[k] = .01

    def observe(offset, x=1., yaw=0.):
        stamp = start + offset
        runtime.observe_pose(NS(header=NS(frame_id="map", stamp=NS(sec=int(stamp), nanosec=int(stamp % 1 * 1e9))),
            pose=NS(covariance=covariance, pose=NS(position=NS(x=x, y=2.),
                orientation=NS(z=math.sin(yaw / 2), w=math.cos(yaw / 2))))))

    observe(0); observe(1)
    assert not runtime.state["localized"]  # Two low-covariance samples are insufficient.
    observe(2); observe(3.1)
    assert runtime.state["localized"]
    observe(4.2, x=1.10)
    assert not runtime.state["localized"]
    observe(5.3, x=1.10); observe(6.4, x=1.10); observe(7.5, x=1.10)
    assert runtime.state["localized"]
    observe(8.6, x=1.10, yaw=.1)
    assert not runtime.state["localized"]
    mode["mode"] = "navigation"
    observe(9.7, x=1.5, yaw=.3)
    assert runtime.state["localized"]  # Intended driving is not stationary drift.
