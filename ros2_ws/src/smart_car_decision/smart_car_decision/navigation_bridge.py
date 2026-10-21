"""Nav2 action adapter. ROS callbacks spin independently of the HTTP loop."""
import asyncio
import copy
import math
import threading
import time
from uuid import uuid4

from geometry_msgs.msg import PoseStamped
from nav_msgs.msg import Path
from nav2_msgs.action import ComputePathToPose, NavigateToPose
from rclpy.action import ActionClient
from action_msgs.msg import GoalStatus

from .navigation_config import drawing_identity, finite_number, map_key, validate_map_goal


async def wait_future(future, timeout=8):
    end = time.monotonic() + timeout
    while not future.done():
        if time.monotonic() >= end:
            raise TimeoutError("导航服务响应超时")
        await asyncio.sleep(.02)
    return future.result()


class NavigationBridge:
    def __init__(self, node, radius=.25):
        self.node, self.radius = node, radius
        self.planner = ActionClient(node, ComputePathToPose, "/compute_path_to_pose")
        self.navigator = ActionClient(node, NavigateToPose, "/navigate_to_pose")
        self.lock = threading.RLock()
        self.state = {"ready": False, "state": "idle", "message": "等待 Nav2 启动", "goal_id": None,
                      "goal": None, "path": [], "distance_remaining": None, "estimated_time_remaining": None}
        self.plans = {}
        self.handle = None
        self.cancel_future = None
        self.epoch = 0
        self.started_at = 0.0
        self.active_map_key = ""
        self.node.create_subscription(Path, "/plan", self.on_path, 2)
        self.node.create_timer(.25, self.watchdog)

    def _health(self):
        if getattr(self.node, "_startup_stop_pending", False):
            return "正在确认车端启动后的停车状态"
        runtime = getattr(self.node, "navigation_runtime", None)
        if runtime:
            error = runtime.health_error()
            if error:
                return error
        if not self.planner.server_is_ready() or not self.navigator.server_is_ready():
            return "车端 Nav2 尚未启动"
        status = self.node.store.snapshot()
        age = self.node.ros_status_age_sec()
        if age is None or age > 2.5:
            return "机器人状态已超时"
        if status.get("emergency_stop"):
            return "请先解除急停"
        if status.get("mode") == "mapping":
            return "请先结束建图并启动导航定位"
        for name, label in (("lidar", "雷达"), ("odom", "里程计"), ("tf", "坐标变换"), ("map_pose", "地图定位")):
            if not status.get(name, {}).get("ok"):
                return f"等待有效的{label}"
        if self.node.map_snapshot.snapshot() is None:
            return "没有实车地图"
        if self.node.navigation_config is None:
            return "导航配置不可用，请检查车端配置文件"
        config = self.node.navigation_config.snapshot()
        calibration = config.get("calibration")
        if not calibration or calibration.get("invalidated") or calibration["map_key"] != map_key(self.node.map_snapshot.snapshot()):
            return "请先将平面图与实车地图对齐"
        if self.node.navigation_map.snapshot() is None:
            return "等待实验室障碍地图"
        return ""

    def snapshot(self):
        with self.lock:
            state = copy.deepcopy(self.state)
        error = self._health()
        state["ready"] = not error
        if error and state["state"] not in {"running", "starting", "failed"}:
            state["message"] = error
        return state

    def _pose(self, goal, frame):
        value = PoseStamped()
        value.header.frame_id = frame
        value.header.stamp = self.node.get_clock().now().to_msg()
        value.pose.position.x = float(goal["x"])
        value.pose.position.y = float(goal["y"])
        value.pose.orientation.z = math.sin(goal["yaw"] / 2)
        value.pose.orientation.w = math.cos(goal["yaw"] / 2)
        return value

    async def plan(self, payload):
        with self.lock:
            error = self._health()
            if error:
                raise RuntimeError(error)
            snapshot = self.node.navigation_map.snapshot()
            calibration = self.node.navigation_config.snapshot()["calibration"]
            calibration_matrix = list(calibration["matrix"])
            calibration_drawing = drawing_identity(calibration.get("drawing"))
            if payload.get("calibration_matrix") != calibration_matrix:
                raise ValueError("地图对齐已变化，请刷新页面后重新规划")
            if "calibration_drawing" in payload and drawing_identity(payload["calibration_drawing"]) != calibration_drawing:
                raise ValueError("平面图已变化，请重新对齐后规划")
        key = map_key(snapshot)
        if payload.get("map_key") != key:
            raise ValueError("地图已变化，请重新选择目标")
        goal = validate_map_goal(payload["goal"], snapshot, self.radius)
        goal["yaw"] = finite_number(payload["goal"].get("yaw", self.node.store.snapshot()["map_pose"]["yaw"]))
        request = ComputePathToPose.Goal()
        request.goal = self._pose(goal, snapshot.get("header", {}).get("frame_id") or "map")
        request.use_start = False
        future = self.planner.send_goal_async(request)
        try:
            handle = await wait_future(future)
        except BaseException:
            def cancel_late(f):
                try:
                    h = f.result()
                    if h.accepted:
                        h.cancel_goal_async()
                except Exception:
                    pass
            future.add_done_callback(cancel_late)
            raise
        if not handle.accepted:
            raise RuntimeError("规划服务拒绝了目标")
        try:
            result = await wait_future(handle.get_result_async())
        except BaseException:
            handle.cancel_goal_async()
            raise
        if result.status != GoalStatus.STATUS_SUCCEEDED or not result.result.path.poses:
            raise ValueError("没有可通行路线，请选择其他位置")
        path = [{"x": p.pose.position.x, "y": p.pose.position.y} for p in result.result.path.poses]
        distance = sum(math.hypot(a["x"] - b["x"], a["y"] - b["y"]) for a, b in zip(path, path[1:]))
        plan_id = str(uuid4())
        plan = {"ok": True, "plan_id": plan_id, "map_key": key, "goal": goal, "path": path, "distance": distance}
        with self.lock:
            current_calibration = self.node.navigation_config.snapshot()["calibration"]
            if (calibration_matrix != current_calibration["matrix"] or
                    calibration_drawing != drawing_identity(current_calibration.get("drawing")) or
                    key != map_key(self.node.map_snapshot.snapshot())):
                raise ValueError("地图或对齐已变化，请重新规划")
            now = time.monotonic()
            self.plans = {i: p for i, p in self.plans.items() if now - p["created"] < 60}
            self.plans[plan_id] = {**plan, "created": now, "calibration_matrix": calibration_matrix,
                                   "calibration_drawing": calibration_drawing}
        return plan

    async def start(self, payload, guard=None):
        while self.cancel_future is not None:
            pending = self.cancel_future
            await wait_future(pending)
            if self.cancel_future is pending:
                self.cancel_future = None
        with self.lock:
            if guard is not None and not guard():
                raise RuntimeError("任务已取消，不再派发目标")
            if self.state["state"] in {"starting", "running"}:
                raise RuntimeError("小车正在导航，请先停止当前导航")
            plan = self.plans.get(payload.get("plan_id"))
            if not plan or time.monotonic() - plan["created"] > 60:
                raise ValueError("路线预览已过期，请重新规划")
            error = self._health()
            if error:
                raise RuntimeError(error)
            snapshot = self.node.navigation_map.snapshot()
            calibration = self.node.navigation_config.snapshot()["calibration"]
            if (calibration["matrix"] != plan["calibration_matrix"] or
                    drawing_identity(calibration.get("drawing")) != plan["calibration_drawing"]):
                raise ValueError("地图对齐已变化，请重新规划")
            if map_key(snapshot) != plan["map_key"]:
                raise ValueError("地图已变化，请重新规划")
            validate_map_goal(plan["goal"], snapshot, self.radius)
            self.epoch += 1
            epoch = self.epoch
            self.started_at = time.monotonic()
            self.active_map_key = plan["map_key"]
            self.state.update(state="starting", message="正在启动导航", goal_id=plan["plan_id"], goal=plan["goal"], path=plan["path"], distance_remaining=plan["distance"])
            self.state["estimated_time_remaining"] = None
            if self.node.set_mode("navigation") != "navigation":
                self.state.update(state="failed", message="车端拒绝了导航模式")
                raise RuntimeError("车端拒绝了导航模式")
        def clean_late(f):
            try:
                handle = f.result()
                if handle.accepted and self.epoch != epoch:
                    handle.cancel_goal_async()
            except Exception:
                pass
        try:
            request = NavigateToPose.Goal()
            request.pose = self._pose(plan["goal"], snapshot.get("header", {}).get("frame_id") or "map")
            future = self.navigator.send_goal_async(request, feedback_callback=lambda f: self.feedback(f, epoch))
            future.add_done_callback(clean_late)
            handle = await wait_future(future)
            if not handle.accepted:
                raise RuntimeError("小车拒绝了导航目标")
            with self.lock:
                if epoch != self.epoch:
                    handle.cancel_goal_async()
                    raise RuntimeError("启动过程已被停止")
                self.handle = handle
                self.state.update(state="running", message="正在前往目的地")
                handle.get_result_async().add_done_callback(lambda f: self.completed(f, epoch))
        except BaseException as exc:
            with self.lock:
                if epoch == self.epoch:
                    self.epoch += 1
                    if self.handle:
                        self.handle.cancel_goal_async()
                    self.handle = None
                    self.state.update(state="failed", message=str(exc))
                    self.node.set_mode("stop")
            raise
        return {"ok": True, "goal_id": plan["plan_id"]}

    def feedback(self, message, epoch):
        f = message.feedback
        with self.lock:
            if epoch != self.epoch:
                return
            self.state["distance_remaining"] = float(f.distance_remaining)
            duration = f.estimated_time_remaining
            self.state["estimated_time_remaining"] = duration.sec + duration.nanosec / 1e9

    def on_path(self, message):
        with self.lock:
            if self.state["state"] == "running":
                self.state["path"] = [{"x": p.pose.position.x, "y": p.pose.position.y} for p in message.poses]

    def completed(self, future, epoch):
        with self.lock:
            if epoch != self.epoch:
                return
            try:
                status = future.result().status
                state = "succeeded" if status == GoalStatus.STATUS_SUCCEEDED else "canceled" if status == GoalStatus.STATUS_CANCELED else "failed"
                self.state.update(state=state, message={"succeeded": "已到达目的地", "canceled": "导航已停止", "failed": "导航失败，请检查现场障碍与定位"}[state])
                if state == "succeeded":
                    self.state["distance_remaining"] = 0.0
            except Exception as exc:
                self.state.update(state="failed", message=f"导航结果异常：{exc}")
            self.handle = None
            self.node.set_mode("stop")

    def cancel(self, message="导航已停止", failed=False):
        with self.lock:
            self.epoch += 1
            handle, self.handle = self.handle, None
            self.state.update(state="failed" if failed else "canceled", message=message)
            self.node.set_mode("stop")
            if handle:
                self.cancel_future = handle.cancel_goal_async()
        return {"ok": True, "message": message}

    def watchdog(self):
        with self.lock:
            if self.state["state"] not in {"starting", "running"}:
                return
            error = self._health()
            if error:
                self.cancel(error, failed=True)
            elif map_key(self.node.map_snapshot.snapshot()) != self.active_map_key:
                self.cancel("地图已变化，导航已停止，请重新对齐并规划", failed=True)
            elif time.monotonic() - self.started_at > 1 and self.node.store.snapshot().get("mode") != "navigation":
                self.cancel("模式已切换，导航已停止")
