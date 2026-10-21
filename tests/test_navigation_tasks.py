import asyncio
import copy
import json
import threading
from types import SimpleNamespace as NS

import pytest

from smart_car_decision.navigation_config import fit_calibration, map_key
from smart_car_decision.navigation_tasks import NavigationTaskRunner
from smart_car_decision.web_api import apply_control_request


class Bridge:
    radius = .25

    def __init__(self):
        self.lock = threading.RLock()
        self.state = {"state": "idle", "goal_id": None, "message": ""}
        self.starts, self.plans = [], []
        self.block = None
        self.error = ""

    def _health(self):
        return self.error

    def snapshot(self):
        return dict(self.state)

    async def plan(self, payload):
        self.plans.append(payload)
        if self.block:
            await self.block.wait()
        return {"plan_id": str(len(self.plans))}

    async def start(self, payload, guard=None):
        if guard and not guard():
            raise RuntimeError("cancelled")
        self.starts.append(payload)
        self.state.update(state="running", goal_id=payload["plan_id"])
        return {"goal_id": payload["plan_id"]}

    def cancel(self, message="cancel", failed=False):
        self.state.update(state="failed" if failed else "canceled", message=message)


def runner(tmp_path):
    grid = {"header": {"frame_id": "map"}, "session_id": "one", "info": {
        "width": 80, "height": 80, "resolution": .1, "origin": {"x": 0, "y": 0, "yaw": 0}}, "data": [0] * 6400}
    drawing = {"kind": "uploaded", "id": "drawing", "name": "lab", "width": 100, "height": 100, "revision": "v1"}
    anchors = [{"drawing": {"x": x, "y": y}, "world": {"x": .08 * x, "y": 8 - .08 * y}}
               for x, y in [(0, 0), (100, 0), (0, 100), (100, 100)]]
    calibration = fit_calibration(anchors, grid, drawing)
    status = {"map_pose": {"x": 1., "y": 1., "yaw": .4}}
    node = NS(navigation=Bridge(), map_snapshot=NS(snapshot=lambda: grid), navigation_map=NS(snapshot=lambda: grid),
              navigation_config=NS(snapshot=lambda: {"calibration": calibration}), store=NS(snapshot=lambda: status),
              set_mode=lambda mode: mode, set_command=lambda cmd: cmd)
    task = NavigationTaskRunner(node, tmp_path / "task.json")
    node.navigation_tasks = task
    payload = {"kind": "delivery", "run_id": "run1", "task_id": "business1", "map_key": map_key(grid), "control_session_id": "one",
               "calibration_matrix": calibration["matrix"], "calibration_drawing": drawing,
               "waypoints": [{"name": "老师处", "drawing": {"x": 50, "y": 50}, "yaw": 1.}], "return_to_start": True}
    return task, node, payload


async def until(predicate):
    for _ in range(100):
        if predicate():
            return
        await asyncio.sleep(.01)
    raise AssertionError("task transition timed out")


def test_delivery_requires_load_and_handover_then_returns(tmp_path):
    async def scenario():
        task, node, payload = runner(tmp_path)
        state = await task.create(payload)
        assert state["state"] == "waiting_load" and not node.navigation.starts
        assert state["goals"][0]["x"] == pytest.approx(4)
        assert state["goals"][0]["yaw"] == pytest.approx(-1)
        await task.action({"run_id": "run1", "action": "loaded"})
        await until(lambda: task.snapshot()["state"] == "running")
        with pytest.raises(RuntimeError):
            await task.action({"run_id": "run1", "action": "handover"})
        node.navigation.state["state"] = "succeeded"
        await until(lambda: task.snapshot()["state"] == "waiting_handover")
        assert len(node.navigation.starts) == 1
        await task.action({"run_id": "run1", "action": "handover"})
        await until(lambda: task.snapshot()["state"] == "returning")
        assert node.navigation.plans[-1]["goal"] == payload_pose()
        node.navigation.state["state"] = "succeeded"
        await until(lambda: task.snapshot()["state"] == "completed")
        assert task.snapshot_for("run1")["state"] == "completed"
    asyncio.run(scenario())


def payload_pose():
    return {"x": 1., "y": 1., "yaw": .4}


def test_patrol_cycles_dwell_pause_and_real_odometry(tmp_path):
    async def scenario():
        task, node, payload = runner(tmp_path)
        payload.update(kind='patrol', cycles=2, dwell_sec=.2, return_to_start=False)
        await task.create(payload)
        await task.action({'run_id': 'run1', 'action': 'start'})
        await until(lambda: task.snapshot()['state'] == 'running')
        task.observe_odometry(0., 0., 1.)
        task.observe_odometry(.1, 0., 1.2)
        task.observe_odometry(99., 0., 1.3)  # localization/odometry jump does not count
        assert task.snapshot()['distance_m'] == pytest.approx(.1)
        node.navigation.state['state'] = 'succeeded'
        await until(lambda: task.snapshot()['state'] == 'dwelling')
        await task.action({'run_id': 'run1', 'action': 'pause'})
        await asyncio.sleep(.3)
        assert len(node.navigation.starts) == 1
        await task.action({'run_id': 'run1', 'action': 'resume'})
        await until(lambda: len(node.navigation.starts) == 2)
        node.navigation.state['state'] = 'succeeded'
        await until(lambda: task.snapshot()['state'] == 'completed')
        state = task.snapshot()
        assert state['completed_stops'] == state['total_stops'] == 2
        assert not state['acceptance_met']
    asyncio.run(scenario())


@pytest.mark.parametrize('values', [{'cycles': True}, {'cycles': 0}, {'cycles': 1.5}, {'dwell_sec': float('nan')}, {'dwell_sec': -1}])
def test_rejects_invalid_patrol_schedule(tmp_path, values):
    async def scenario():
        task, _, payload = runner(tmp_path)
        payload.update(kind='patrol', **values)
        with pytest.raises(ValueError):
            await task.create(payload)
    asyncio.run(scenario())


@pytest.mark.parametrize("control", [{"target": "manual_cmd", "value": "stop"}, {"target": "mode", "value": "stop"}])
def test_stop_during_planning_never_starts_a_late_goal(tmp_path, control):
    async def scenario():
        task, node, payload = runner(tmp_path)
        node.navigation.block = asyncio.Event()
        await task.create(payload)
        await task.action({"run_id": "run1", "action": "loaded"})
        await until(lambda: bool(node.navigation.plans))
        apply_control_request(node, control)
        node.navigation.block.set()
        await asyncio.sleep(.05)
        assert task.snapshot()["state"] == "cancelled"
        assert node.navigation.starts == []
    asyncio.run(scenario())


def test_pause_resume_replans_and_stale_goal_cannot_advance(tmp_path):
    async def scenario():
        task, node, payload = runner(tmp_path)
        await task.create(payload)
        await task.action({"run_id": "run1", "action": "loaded"})
        await until(lambda: task.snapshot()["state"] == "running")
        await task.action({"run_id": "run1", "action": "pause"})
        assert task.snapshot()["state"] == "paused"
        await task.action({"run_id": "run1", "action": "resume"})
        await until(lambda: len(node.navigation.starts) == 2)
        node.navigation.state.update(goal_id="different", state="succeeded")
        await until(lambda: task.snapshot()["state"] == "failed")
        assert not task.snapshot()["completed_stops"]
    asyncio.run(scenario())


def test_patrol_executes_each_stop_and_return_and_retry_does_not_dispatch(tmp_path):
    async def scenario():
        task, node, payload = runner(tmp_path)
        payload.update(kind="patrol", waypoints=payload["waypoints"] * 2)
        await task.create(payload)
        await task.action({"run_id": "run1", "action": "start"})
        for count in (1, 2, 3):
            await until(lambda: len(node.navigation.starts) == count)
            node.navigation.state["state"] = "succeeded"
            await asyncio.sleep(.12)
        await until(lambda: task.snapshot()["state"] == "completed")
        await task.create(payload)
        assert len(node.navigation.starts) == 3
    asyncio.run(scenario())


def test_restart_stops_and_preserves_failed_history(tmp_path):
    task, node, payload = runner(tmp_path)
    asyncio.run(task.create(payload))
    modes = []
    node.set_mode = modes.append
    restored = NavigationTaskRunner(node, tmp_path / "task.json")
    assert restored.snapshot()["state"] == "failed" and modes == ["stop"]
    assert restored.snapshot_for("run1")["state"] == "failed"


def test_map_identity_and_disk_failure_never_start_motion(tmp_path, monkeypatch):
    task, node, payload = runner(tmp_path)
    wrong = copy.deepcopy(payload)
    wrong["map_key"] += "different"
    with pytest.raises(ValueError):
        asyncio.run(task.create(wrong))
    def full(*args, **kwargs):
        raise OSError("disk full")
    monkeypatch.setattr("smart_car_decision.navigation_tasks.os.replace", full)
    with pytest.raises(OSError):
        asyncio.run(task.create(payload))
    assert task.snapshot()["state"] == "idle" and not node.navigation.starts


def test_invalid_persistent_json_is_preserved(tmp_path):
    path = tmp_path / "task.json"
    path.write_text("[]")
    with pytest.raises(ValueError):
        NavigationTaskRunner(NS(), path)
    assert path.read_text() == "[]"


def test_cancel_unconfirmed_request_creates_tombstone_and_blocks_delayed_create(tmp_path):
    async def scenario():
        task, node, payload = runner(tmp_path)
        result = await task.action({"run_id": "run1", "task_id": "business1", "kind": "delivery", "action": "cancel"})
        assert result["state"] == "cancelled" and task.snapshot()["state"] == "idle"
        with pytest.raises(RuntimeError):
            await task.create(payload)
        assert not node.navigation.starts
    asyncio.run(scenario())


def test_current_index_failure_keeps_created_run_cancellable(tmp_path, monkeypatch):
    task, node, payload = runner(tmp_path)
    original = __import__("smart_car_decision.navigation_tasks", fromlist=["_write_record"])._write_record
    def write(path, value):
        if path == task.path:
            raise OSError("current index full")
        original(path, value)
    monkeypatch.setattr("smart_car_decision.navigation_tasks._write_record", write)
    with pytest.raises(OSError):
        asyncio.run(task.create(payload))
    assert task.snapshot()["run_id"] == "run1"
    monkeypatch.setattr("smart_car_decision.navigation_tasks._write_record", original)
    result = asyncio.run(task.action({"run_id": "run1", "action": "cancel"}))
    assert result["state"] == "cancelled" and not node.navigation.starts
