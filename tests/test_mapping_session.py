from types import SimpleNamespace
import signal
import subprocess
import time

import pytest

from smart_car_decision.mapping_session import MapSnapshotStore, MappingRestartManager, slam_process_ids


def grid(stamp=100, data=None, width=2, height=2):
    return SimpleNamespace(
        header=SimpleNamespace(frame_id="map", stamp=SimpleNamespace(sec=stamp, nanosec=0)),
        info=SimpleNamespace(width=width, height=height, resolution=.05,
                             origin=SimpleNamespace(position=SimpleNamespace(x=0., y=0.),
                                                    orientation=SimpleNamespace(x=0., y=0., z=0., w=1.))),
        data=[0, 100, -1, 0] if data is None else data,
    )


class Logger:
    def info(self, message):
        pass

    def error(self, message):
        pass


def test_save_exports_exactly_the_snapshot_used_for_files(tmp_path):
    store = MapSnapshotStore()
    store.update(grid())
    exported = store.save(tmp_path, include_snapshot=True)
    store.update(grid(stamp=101, data=[100, 100, 0, 0]))
    assert exported["snapshot"]["data"] == [0, 100, -1, 0]
    assert exported["snapshot"]["revision"] == 1
    from pathlib import Path
    assert Path(exported["pgm_path"]).read_bytes().endswith(bytes([205, 254, 254, 0]))


class Process:
    pid = 9000
    returncode = None

    def poll(self):
        return self.returncode


def manager(monkeypatch):
    store = MapSnapshotStore()
    manager = MappingRestartManager(Logger(), store, ros_now_ns=lambda: 100_000_000_000)
    monkeypatch.setattr(manager, "_stop_existing_slam", lambda: None)
    monkeypatch.setattr(manager, "_start_slam", lambda: Process())
    return manager, store


def healthy_status():
    now = time.time()
    return {"lidar": {"ok": True, "scan_age_sec": .1}, "odom": {"ok": True, "odom_age_sec": .1},
            "tf": {"ok": True, "checked_at": now},
            "map_pose": {"ok": True, "updated_at": now, "age_sec": 0.}}


def test_session_clear_rejects_old_and_reordered_map_and_counts_expansion(monkeypatch):
    control, store = manager(monkeypatch)
    assert control.on_map(grid(90))
    result = control.restart()
    assert result["mapping"]["state"] == "waiting_map"
    assert store.snapshot() is None
    assert not control.on_map(grid(99))
    assert control.on_map(grid(100))
    first = store.snapshot()
    assert first["revision"] == 1 and first["session_id"] == result["session_id"]
    assert control.on_map(grid(101, [0] * 6, width=3))
    assert store.snapshot()["revision"] == 2
    assert not control.on_map(grid(100))
    assert store.snapshot()["info"]["width"] == 3
    result2 = control.restart()
    assert result2["session_id"] != result["session_id"]
    assert store.snapshot() is None


def test_invalid_or_unknown_map_cannot_be_first_map():
    store = MapSnapshotStore()
    assert not store.update(grid(data=[-1] * 4))
    assert not store.update(grid(data=[0]))
    assert store.snapshot() is None


def test_exit_mapping_keeps_last_grid_and_rejects_late_messages(monkeypatch):
    control, store = manager(monkeypatch)
    control.restart()
    control.on_map(grid(101))
    before = store.snapshot()
    stopped = []
    monkeypatch.setattr(control, "_stop_existing_slam", lambda: stopped.append(True))
    control.stop_mapping()
    assert stopped == [True]
    assert control.snapshot()["state"] == "idle"
    assert not control.on_map(grid(102, data=[100] * 4))
    control.observe_status(healthy_status())
    assert store.snapshot() == before
    assert control.snapshot()["state"] == "idle"
    control.restart()
    assert control.on_map(grid(103))


def test_navigation_load_accepts_map_server_after_mapping_frozen(monkeypatch):
    control, store = manager(monkeypatch)
    control.on_map(grid(101))
    control.stop_mapping()
    control.stop_for_navigation()
    assert store.snapshot() is None
    assert control.on_map(grid(102))


def test_rejects_invalid_grid_values_and_geometry_before_copy():
    store = MapSnapshotStore()
    assert not store.update(grid(data=[0, 101, 0, 0]))
    assert not store.update(grid(data=[0, -2, 0, 0]))
    assert not store.update(grid(width=20000))
    malformed = grid()
    malformed.info.origin.position.x = float("nan")
    assert not store.update(malformed)
    malformed = grid()
    malformed.info.origin.orientation.w = float("inf")
    assert not store.update(malformed)
    assert store.snapshot() is None


def test_readiness_requires_new_map_and_fresh_inputs(monkeypatch):
    control, store = manager(monkeypatch)
    control.restart()
    control.observe_status(healthy_status())
    assert control.snapshot()["state"] == "waiting_map"
    old_pose = healthy_status()
    old_pose["map_pose"]["age_sec"] = .5
    control.observe_status(old_pose)
    control.on_map(grid())
    assert control.snapshot()["state"] == "waiting_map"
    healthy = healthy_status()
    healthy["odom"]["odom_age_sec"] = 4
    control.observe_status(healthy)
    assert control.snapshot()["state"] == "waiting_map"
    control.observe_status(healthy_status())
    assert control.snapshot()["state"] == "ready"


def test_timeout_has_missing_input_diagnostics(monkeypatch):
    control, store = manager(monkeypatch)
    control.restart()
    control._started_monotonic -= 16
    status = control.snapshot()
    assert status["state"] == "error"
    assert "15 秒" in status["error"] and "有效首张地图" in status["error"]


def test_malformed_status_and_stale_actual_tf_cannot_declare_ready(monkeypatch):
    control, store = manager(monkeypatch)
    control.restart()
    control.on_map(grid())
    for payload in (None, [], {"lidar": [], "odom": {"ok": True, "odom_age_sec": "bad"},
                              "map_pose": {"ok": True, "age_sec": float("nan")}, "tf": True}):
        control.observe_status(payload)
        assert control.snapshot()["state"] == "waiting_map"
    payload = healthy_status()
    payload["tf"]["age_sec"] = 2.
    control.observe_status(payload)
    assert control.snapshot()["state"] == "waiting_map"
    payload["tf"]["age_sec"] = .1
    control.observe_status(payload)
    assert control.snapshot()["state"] == "ready"


def test_start_failure_and_later_exit_are_visible(monkeypatch):
    control, store = manager(monkeypatch)
    def fail():
        raise OSError("missing executable")
    monkeypatch.setattr(control, "_start_slam", fail)
    with pytest.raises(RuntimeError, match="missing executable"):
        control.restart()
    assert control.snapshot()["state"] == "error"
    monkeypatch.setattr(control, "_start_slam", lambda: Process())
    control.restart()
    control._process.returncode = 2
    assert "退出码 2" in control.snapshot()["error"]


def test_precise_slam_identification_ignores_command_substrings(tmp_path, monkeypatch):
    entries = {"1": "/opt/ros/humble/lib/slam_toolbox/async_slam_toolbox_node",
               "2": "/usr/bin/python3", "3": "/usr/bin/bash", "4": "/opt/ros/humble/lib/slam_toolbox/sync_slam_toolbox_node"}
    for name in entries:
        (tmp_path / name).mkdir()
    monkeypatch.setattr("smart_car_decision.mapping_session.os.readlink", lambda path: entries[path.parent.name])
    assert sorted(slam_process_ids(tmp_path)) == [1, 4]


def test_stop_waits_for_actual_exit_without_fixed_sleep(monkeypatch):
    control = MappingRestartManager(Logger(), MapSnapshotStore())
    calls, sleeps = [], []
    states = iter([[12], [12], [], [], []])
    monkeypatch.setattr("smart_car_decision.mapping_session.slam_process_ids", lambda: next(states))
    monkeypatch.setattr("smart_car_decision.mapping_session.os.kill", lambda pid, sig: calls.append((pid, sig)))
    monkeypatch.setattr("smart_car_decision.mapping_session.time.sleep", lambda value: sleeps.append(value))
    control._stop_existing_slam()
    assert calls == [(12, signal.SIGTERM)]
    assert sleeps == [.05]


class WaitProcess(Process):
    def __init__(self, hang_once=False, returncode=None):
        self.wait_calls = []
        self.hang_once = hang_once
        self.returncode = returncode

    def wait(self, timeout):
        self.wait_calls.append(timeout)
        if self.hang_once:
            self.hang_once = False
            raise subprocess.TimeoutExpired("owned slam launch", timeout)
        self.returncode = 0
        return 0


@pytest.mark.parametrize("hang_once", [False, True])
def test_close_signals_owned_group_waits_and_is_idempotent(monkeypatch, hang_once):
    control = MappingRestartManager(Logger(), MapSnapshotStore())
    owned = WaitProcess(hang_once)
    control._process = owned
    calls = []
    monkeypatch.setattr("smart_car_decision.mapping_session.os.killpg", lambda pid, sig: calls.append((pid, sig)), raising=False)
    monkeypatch.setattr("smart_car_decision.mapping_session.signal.SIGKILL", 9, raising=False)
    monkeypatch.setattr("smart_car_decision.mapping_session.slam_process_ids", lambda: pytest.fail("shutdown must not discover external SLAM"))
    control.close()
    expected = [(owned.pid, signal.SIGTERM)] + ([(owned.pid, 9)] if hang_once else [])
    assert calls == expected
    assert owned.wait_calls == ([3, 3] if hang_once else [3])
    assert control._process is None
    control.close()
    assert calls == expected
    with pytest.raises(RuntimeError, match="关闭"):
        control.restart()


def test_close_without_owned_process_never_touches_external_slam(monkeypatch):
    control = MappingRestartManager(Logger(), MapSnapshotStore())
    monkeypatch.setattr("smart_car_decision.mapping_session.slam_process_ids", lambda: pytest.fail("must not scan external processes"))
    monkeypatch.setattr("smart_car_decision.mapping_session.os.killpg", lambda *args: pytest.fail("no group is owned"), raising=False)
    monkeypatch.setattr("smart_car_decision.mapping_session.os.kill", lambda *args: pytest.fail("must not kill external SLAM"))
    control.close()
    assert control.snapshot()["state"] == "idle"


def test_close_reaps_already_exited_owned_process_without_signaling(monkeypatch):
    control = MappingRestartManager(Logger(), MapSnapshotStore())
    owned = WaitProcess(returncode=2)
    control._process = owned
    monkeypatch.setattr("smart_car_decision.mapping_session.os.killpg", lambda *args: pytest.fail("exited launch group is not signaled"), raising=False)
    control.close()
    assert owned.wait_calls == [3]


def test_status_and_map_api_expose_session_without_dropping_legacy_fields(fake_node):
    from fastapi.testclient import TestClient
    from smart_car_decision.web_api import create_app
    control = MappingRestartManager(Logger(), MapSnapshotStore())
    fake_node.mapping_restart = control
    fake_node.map_snapshot = control._map_snapshot
    control.on_map(grid())
    client = TestClient(create_app(fake_node))
    status = client.get("/api/status").json()
    assert status["mapping"]["state"] == "idle"
    snapshot = client.get("/api/map").json()
    assert snapshot["session_id"] == status["mapping"]["session_id"]
    assert snapshot["revision"] == 1 and "info" in snapshot and "data" in snapshot
