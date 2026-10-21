"""Local UI QA fixture. No ROS imports, topics or physical vehicle connection."""
import math
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "ros2_ws/src/smart_car_decision"))
from conftest import FakeWebNode
from test_navigation_config import anchors, lab_map
from smart_car_decision.navigation_config import NavigationConfigStore, map_key, validate_map_goal
from smart_car_decision.web_api import create_app


class SimulatedNavigation:
    def __init__(self, node):
        self.node = node
        self.plans = {}
        self.state = {"ready": True, "state": "idle", "message": "导航服务已就绪", "goal_id": None,
                      "goal": None, "path": [], "distance_remaining": None, "estimated_time_remaining": None}

    def snapshot(self):
        return dict(self.state)

    async def plan(self, payload):
        if payload["map_key"] != map_key(self.node.map_snapshot.snapshot()):
            raise ValueError("地图已变化")
        goal = payload["goal"]
        validate_map_goal(goal, self.node.map_snapshot.snapshot())
        start = self.node.store.snapshot()["map_pose"]
        plan = {"ok": True, "plan_id": str(time.monotonic()), "map_key": payload["map_key"], "goal": goal,
                "path": [{"x": start["x"], "y": start["y"]}, {"x": goal["x"], "y": goal["y"]}],
                "distance": math.hypot(start["x"] - goal["x"], start["y"] - goal["y"])}
        self.plans[plan["plan_id"]] = plan
        return plan

    async def start(self, payload):
        plan = self.plans[payload["plan_id"]]
        self.node.set_mode("navigation")
        self.state.update(state="running", message="正在前往目的地", goal_id=plan["plan_id"], goal=plan["goal"], path=plan["path"], distance_remaining=plan["distance"])
        return {"ok": True, "goal_id": plan["plan_id"]}

    def cancel(self, message="导航已停止"):
        self.node.set_mode("stop")
        self.state.update(state="canceled", message=message)
        return {"ok": True}


def app():
    node = FakeWebNode(ros_status_age_sec=.1)
    node.store.update(lidar={"ok": True}, map={"ok": True}, odom={"ok": True}, tf={"ok": True},
                      map_pose={"ok": True, "x": 10.78, "y": .42, "yaw": math.pi / 2}, updated_at=time.time())
    snapshot = lab_map()
    snapshot["updated_at"] = time.time()
    snapshot["header"]["stamp"] = {"sec": 1, "nanosec": 0}
    node.map_snapshot.update(snapshot)
    node.navigation_config = NavigationConfigStore(ROOT / "output/navigation-browser-fixture.json")
    node.navigation_config.calibrate(anchors(), lab_map())
    node.navigation = SimulatedNavigation(node)
    return create_app(node)


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app(), host="127.0.0.1", port=8098, log_level="warning")
