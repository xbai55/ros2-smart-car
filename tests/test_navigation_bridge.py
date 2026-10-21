"""Exercise real bridge lifecycle code with action messages/clients replaced."""
import asyncio
import importlib.util
import sys
from concurrent.futures import Future
from pathlib import Path
from types import ModuleType, SimpleNamespace as NS

import pytest

from smart_car_decision.navigation_config import map_key, fit_calibration
from smart_car_decision.navigation_map import NavigationMapStore
from test_navigation_config import lab_map, anchors


def finished(value):
    future = Future()
    future.set_result(value)
    return future


class GoalHandle:
    accepted = True

    def __init__(self, result=None):
        self.cancels = 0
        self.result = finished(result) if result else Future()

    def cancel_goal_async(self):
        self.cancels += 1
        return finished(None)

    def get_result_async(self):
        return self.result


class Client:
    ready = True

    def __init__(self, *args):
        self.requests = []
        self.response = Future()

    def server_is_ready(self):
        return self.ready

    def send_goal_async(self, request, **kwargs):
        self.requests.append(request)
        return self.response


@pytest.fixture
def bridge(monkeypatch, make_fake_node):
    def module(name, **values):
        mod = ModuleType(name)
        mod.__dict__.update(values)
        monkeypatch.setitem(sys.modules, name, mod)
    class PoseStamped:
        def __init__(self):
            self.header = NS(frame_id="", stamp=None)
            self.pose = NS(position=NS(x=0., y=0.), orientation=NS(z=0., w=1.))
    module("geometry_msgs.msg", PoseStamped=PoseStamped)
    module("nav_msgs.msg", Path=object)
    module("nav2_msgs.action", ComputePathToPose=NS(Goal=NS), NavigateToPose=NS(Goal=NS))
    module("rclpy.action", ActionClient=Client)
    module("action_msgs.msg", GoalStatus=NS(STATUS_SUCCEEDED=4, STATUS_CANCELED=5))
    path = Path(__file__).resolve().parents[1] / "ros2_ws/src/smart_car_decision/smart_car_decision/navigation_bridge.py"
    spec = importlib.util.spec_from_file_location("smart_car_decision.bridge_under_test", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    node = make_fake_node(ros_status_age_sec=.1)
    node.store.update(lidar={"ok": True}, odom={"ok": True}, tf={"ok": True}, map_pose={"ok": True, "x": 1, "y": 1, "yaw": 0})
    node.map_snapshot.update(lab_map())
    calibration = fit_calibration(anchors(), lab_map())
    node.navigation_config = NS(snapshot=lambda: {"calibration": calibration})
    node.navigation_map = NavigationMapStore()
    node.navigation_map.update(lab_map(), calibration)
    node.create_subscription = lambda *a: None
    node.create_timer = lambda *a: None
    node.get_clock = lambda: NS(now=lambda: NS(to_msg=lambda: None))
    return mod.NavigationBridge(node)


def preview(bridge):
    poses = [NS(pose=NS(position=NS(x=x, y=2.7))) for x in (1, 2, 3)]
    bridge.planner.response = finished(GoalHandle(NS(status=4, result=NS(path=NS(poses=poses)))))
    return asyncio.run(bridge.plan({"map_key": map_key(lab_map()), "goal": {"x": 3, "y": 2.7, "yaw": 0}, "calibration_matrix": bridge.node.navigation_config.snapshot()["calibration"]["matrix"]}))


def test_preview_does_not_change_mode_and_completion_stops(bridge):
    plan = preview(bridge)
    assert bridge.node.mode_commands == []
    handle = GoalHandle()
    bridge.navigator.response = finished(handle)
    asyncio.run(bridge.start({"plan_id": plan["plan_id"]}))
    assert bridge.snapshot()["state"] == "running"
    assert bridge.node.mode_commands[-1] == "navigation"
    handle.result.set_result(NS(status=4))
    assert bridge.snapshot()["state"] == "succeeded"
    assert bridge.node.mode_commands[-1] == "stop"


def test_startup_requires_an_observed_stop_before_accepting_navigation(bridge):
    bridge.node._startup_stop_pending = True
    assert "停车状态" in bridge._health()
    with pytest.raises(RuntimeError):
        preview(bridge)
    bridge.node._startup_stop_pending = False
    assert bridge._health() == ""


def test_cancel_during_acceptance_cancels_late_goal_and_cannot_resume(bridge):
    plan = preview(bridge)
    handle = GoalHandle()
    async def scenario():
        task = asyncio.create_task(bridge.start({"plan_id": plan["plan_id"]}))
        await asyncio.sleep(.001)
        bridge.cancel()
        bridge.navigator.response.set_result(handle)
        with pytest.raises(RuntimeError, match="已被停止"):
            await task
    asyncio.run(scenario())
    assert handle.cancels >= 1
    assert bridge.snapshot()["state"] == "canceled"
    assert bridge.node.mode_commands[-1] == "stop"
    handle.result.set_result(NS(status=4))
    assert bridge.snapshot()["state"] == "canceled"


@pytest.mark.parametrize("failure", ["map", "lidar", "service"])
def test_watchdog_cancels_on_changed_map_or_lost_health(bridge, failure):
    plan = preview(bridge)
    handle = GoalHandle()
    bridge.navigator.response = finished(handle)
    asyncio.run(bridge.start({"plan_id": plan["plan_id"]}))
    if failure == "map":
        snapshot = lab_map()
        snapshot["info"]["origin"]["x"] += 1
        bridge.node.map_snapshot.update(snapshot)
    elif failure == "lidar":
        bridge.node.store.update(lidar={"ok": False})
    else:
        bridge.navigator.ready = False
    bridge.watchdog()
    assert bridge.snapshot()["state"] == "failed"
    assert handle.cancels == 1
    assert bridge.node.mode_commands[-1] == "stop"


def test_stale_preview_and_send_failure_never_leave_motion_enabled(bridge):
    plan = preview(bridge)
    bridge.plans[plan["plan_id"]]["created"] -= 61
    with pytest.raises(ValueError, match="过期"):
        asyncio.run(bridge.start({"plan_id": plan["plan_id"]}))
    assert bridge.node.mode_commands == []
    plan = preview(bridge)
    def fail(*a, **kw):
        raise RuntimeError("action unavailable")
    bridge.navigator.send_goal_async = fail
    with pytest.raises(RuntimeError):
        asyncio.run(bridge.start({"plan_id": plan["plan_id"]}))
    assert bridge.node.mode_commands[-1] == "stop"
    assert bridge.snapshot()["state"] == "failed"


def test_obsolete_registration_cannot_plan_or_start(bridge):
    with pytest.raises(ValueError, match="对齐已变化"):
        asyncio.run(bridge.plan({"map_key": map_key(lab_map()), "goal": {"x": 3, "y": 2.7}, "calibration_matrix": [1, 0, 0, 0, 1, 0]}))
    plan = preview(bridge)
    bridge.node.navigation_config.snapshot()["calibration"]["matrix"][2] += .1
    with pytest.raises(ValueError, match="对齐已变化"):
        asyncio.run(bridge.start({"plan_id": plan["plan_id"]}))
    assert bridge.node.mode_commands == []


def test_stale_uploaded_drawing_cannot_plan_or_start_even_with_same_matrix(bridge):
    from test_navigation_config import uploaded_drawing
    calibration = bridge.node.navigation_config.snapshot()["calibration"]
    with pytest.raises(ValueError, match="平面图已变化"):
        asyncio.run(bridge.plan({"map_key": map_key(lab_map()), "goal": {"x": 3, "y": 2.7},
                                "calibration_matrix": calibration["matrix"], "calibration_drawing": uploaded_drawing()}))
    plan = preview(bridge)
    calibration["drawing"] = uploaded_drawing()
    with pytest.raises(ValueError, match="对齐已变化"):
        asyncio.run(bridge.start({"plan_id": plan["plan_id"]}))
    assert bridge.node.mode_commands == []


def test_invalidated_registration_blocks_cached_preview_and_planning(bridge):
    plan = preview(bridge)
    bridge.node.navigation_config.snapshot()["calibration"]["invalidated"] = True
    assert not bridge.snapshot()["ready"]
    with pytest.raises(RuntimeError, match="对齐"):
        asyncio.run(bridge.start({"plan_id": plan["plan_id"]}))
    with pytest.raises(RuntimeError, match="对齐"):
        preview(bridge)
    assert bridge.node.mode_commands == []
