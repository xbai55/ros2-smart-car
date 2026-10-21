"""Own one Nav2 launch and accept localization only after an explicit pose seed."""
import copy
from contextlib import nullcontext
import hashlib
import json
import math
import os
from pathlib import Path
import signal
import subprocess
import threading
import time

from .map_assets import save_occupancy_snapshot
from .navigation_config import finite_number, validate_map_goal
from .keepout import validate_keepout, inflate_keepout


def validate_asset(payload):
    snapshot = copy.deepcopy(payload["snapshot"])
    info = snapshot["info"]
    width, height = info["width"], info["height"]
    if (type(width) is not int or type(height) is not int or min(width, height) <= 0 or
            max(width, height) > 16384 or width * height > 16_000_000):
        raise ValueError("地图尺寸无效")
    if finite_number(info["resolution"]) <= 0:
        raise ValueError("地图分辨率无效")
    for key in ("x", "y", "yaw"):
        finite_number(info["origin"][key])
    data = snapshot["data"]
    if (not isinstance(data, list) or len(data) != width * height or
            any(type(v) is not int or not -1 <= v <= 100 for v in data) or all(v < 0 for v in data)):
        raise ValueError("栅格数据无效")
    validate_keepout(snapshot)
    if snapshot.get("header", {}).get("frame_id") != "map":
        raise ValueError("导航地图必须使用 map 坐标系")
    raw = json.dumps(snapshot, ensure_ascii=False, allow_nan=False, separators=(",", ":")).encode()
    digest = hashlib.sha256(raw).hexdigest()
    if payload.get("digest") != digest:
        raise ValueError("地图版本校验失败")
    return snapshot, digest


class NavigationRuntime:
    def __init__(self, node, directory="~/.ros/insightrover/navigation-maps"):
        self.node, self.directory = node, Path(directory).expanduser()
        self.lock = threading.RLock()
        self.operation_lock = threading.RLock()
        self.process = None
        self.pose_window = []
        self.expected_keepout = None
        self.keepout_received = False
        self.keepout_info_received = False
        self.state = {"state": "idle", "message": "请选择 SLAM 地图并加载定位导航", "map_id": None,
                      "digest": None, "localized": False, "initial_pose_at": None, "pose_at": None}

    def stationary(self):
        status = self.node.store.snapshot()
        age = self.node.ros_status_age_sec()
        odom = status.get("odom", {})
        if age is None or age > 2.5 or not odom.get("ok"):
            raise RuntimeError("等待有效里程计与小车状态")
        if "linear_speed_xy" not in odom:
            raise RuntimeError("请配套更新车端状态节点，以确认横向与纵向速度均为零")
        if status.get("mode") != "stop" or abs(finite_number(odom["linear_speed_xy"])) > .01 or abs(finite_number(odom.get("angular_speed", 1))) > .03:
            raise RuntimeError("请先停止小车，再加载地图或设置初始位置")

    def load(self, payload):
        snapshot, digest = validate_asset(payload)
        with self.operation_lock, getattr(self.node.navigation, "lock", nullcontext()):
            if payload.get("control_session_id") != self.node.map_snapshot.session_id:
                raise ValueError("控制连接已变化，请刷新并核对小车后再加载地图")
            self.stationary()
            if self.node.navigation and self.node.navigation.snapshot()["state"] in {"starting", "running"}:
                raise RuntimeError("请先取消当前导航")
            tasks = getattr(self.node, "navigation_tasks", None)
            if tasks and tasks.active:
                raise RuntimeError("请先取消当前运输或巡航任务")
            # Never launch a second independently managed Nav2 stack.
            if self.process is None and self.node.navigation and self.node.navigation.navigator.server_is_ready():
                raise RuntimeError("检测到外部 Nav2，请先停止该导航栈后再从本页加载")
            self.node.set_command("stop")
            self.node.set_mode("stop")
            self.stop()
            self.state.update(state="loading", digest=digest, localized=False)
            self.node.mapping_restart.stop_for_navigation()
            self.node.map_snapshot.expect_asset(snapshot, digest)
            if self.node.navigation_config:
                self.node.navigation_config.invalidate_calibration()
            self.node.refresh_navigation_map()
            folder = self.directory / digest
            folder.mkdir(parents=True, exist_ok=True)
            files = save_occupancy_snapshot(snapshot, folder, "map")
            mask_files = None
            self.expected_keepout = None
            self.keepout_received = False
            self.keepout_info_received = False
            if any(snapshot.get('keepout',[])):
                mask_snapshot = copy.deepcopy(snapshot)
                radius = getattr(self.node.navigation,'radius',.25)
                mask_snapshot['data'] = inflate_keepout(snapshot['keepout'],snapshot['info']['width'],snapshot['info']['height'],snapshot['info']['resolution'],radius)
                mask_snapshot.pop('keepout',None)
                mask_files = save_occupancy_snapshot(mask_snapshot,folder,'keepout')
                self.expected_keepout = mask_snapshot
            self.state = {"state": "starting", "message": "正在启动定位导航，随后请设置小车初始位置", "map_id": payload.get("map_id"),
                          "digest": digest, "localized": False, "initial_pose_at": None, "pose_at": None}
            try:
                with (folder / "navigation.log").open("ab", buffering=0) as log:
                    command = ["ros2", "launch", "smart_car_decision", "navigation.launch.py", f"map:={files['yaml_path']}", f"robot_radius:={getattr(self.node,'navigation_radius',.25)}"]
                    if mask_files: command.append(f"keepout:={mask_files['yaml_path']}")
                    self.process = subprocess.Popen(command,
                                                    stdout=log, stderr=subprocess.STDOUT, start_new_session=True, env=os.environ.copy())
                if self.process.poll() is not None:
                    raise RuntimeError("定位导航启动失败，请检查 navigation.log")
            except (OSError, RuntimeError) as exc:
                self.state.update(state="failed", message=str(exc))
                raise RuntimeError(str(exc)) from exc
            return self.snapshot()

    def seed(self, payload):
        from geometry_msgs.msg import PoseWithCovarianceStamped
        with self.operation_lock, self.lock:
            self.stationary()
            if not self.state["digest"] or self.process is None or self.process.poll() is not None:
                raise RuntimeError("请先加载保存的 SLAM 地图")
            snapshot = self.node.map_snapshot.snapshot()
            if payload.get("asset_digest") != self.state["digest"]:
                raise ValueError("导航地图已变化，请重新选择初始位置")
            if not snapshot or snapshot.get("asset_digest") != self.state["digest"]:
                raise RuntimeError("等待所选地图加载完成")
            p = validate_map_goal(payload, snapshot, 0)
            yaw = finite_number(payload["yaw"])
            if self.node.initial_pose_pub.get_subscription_count() == 0:
                raise RuntimeError("等待 AMCL 初始位置接口就绪")
            message = PoseWithCovarianceStamped()
            message.header.frame_id = "map"
            message.header.stamp = self.node.get_clock().now().to_msg()
            message.pose.pose.position.x, message.pose.pose.position.y = p["x"], p["y"]
            message.pose.pose.orientation.z, message.pose.pose.orientation.w = math.sin(yaw / 2), math.cos(yaw / 2)
            message.pose.covariance[0] = message.pose.covariance[7] = .25 ** 2
            message.pose.covariance[35] = math.radians(15) ** 2
            self.state.update(state="localizing", localized=False, initial_pose_at=time.time(), pose_at=None,
                              good_samples=0, pose_stamp=0,
                              message="初始位置已发送，等待 AMCL 定位收敛")
            self.pose_window = []
            self.node.initial_pose_pub.publish(message)
            return self.snapshot()

    def observe_pose(self, message):
        with self.lock:
            stamp = message.header.stamp.sec + message.header.stamp.nanosec / 1e9
            seeded = self.state.get("initial_pose_at")
            if not seeded or stamp < seeded or stamp <= self.state.get("pose_stamp", 0) or message.header.frame_id != "map":
                return
            covariance = message.pose.covariance
            values = [float(covariance[k]) for k in (0, 7, 35)]
            pose = message.pose.pose
            finite_pose = all(math.isfinite(v) for v in (pose.position.x, pose.position.y, pose.orientation.z, pose.orientation.w))
            good = finite_pose and all(math.isfinite(v) and v > 0 for v in values) and max(values[:2]) <= .25 ** 2 and values[2] <= math.radians(15) ** 2
            count = self.state.get("good_samples", 0) + 1 if good else 0
            good = good and count >= 2
            store = getattr(self.node, "store", None)
            checking_stability = store is not None and store.snapshot().get("mode") == "stop"
            stable = True
            if checking_stability:
                if count:
                    yaw = math.atan2(2 * pose.orientation.w * pose.orientation.z,
                                     1 - 2 * pose.orientation.z ** 2)
                    self.pose_window.append((stamp, pose.position.x, pose.position.y, yaw))
                    # Retain one sample preceding the three-second boundary.
                    while len(self.pose_window) > 2 and self.pose_window[1][0] <= stamp - 3:
                        self.pose_window.pop(0)
                    xs = [p[1] for p in self.pose_window]
                    ys = [p[2] for p in self.pose_window]
                    angles = [math.atan2(math.sin(p[3] - self.pose_window[0][3]),
                                         math.cos(p[3] - self.pose_window[0][3])) for p in self.pose_window]
                    stable = (len(self.pose_window) >= 3 and stamp - self.pose_window[0][0] >= 3
                              and math.hypot(max(xs) - min(xs), max(ys) - min(ys)) <= .05
                              and max(angles) - min(angles) <= math.radians(3))
                else:
                    self.pose_window = []
                    stable = False
            else:
                # Moving navigation must not be mistaken for localization drift.
                self.pose_window = []
            good = good and stable
            self.state.update(localized=good, pose_at=time.time(), pose_stamp=stamp, good_samples=count, state="ready" if good else "localizing",
                              message=("定位检查通过，请核对雷达与地图重合" if good else
                                       "定位仍在调整，请保持静止并核对雷达与地图重合" if checking_stability and count >= 2 else
                                       "定位尚未收敛，请核对初始位置与朝向"))

    def health_error(self):
        if self.expected_keepout is not None and not (self.keepout_received and self.keepout_info_received):
            return '禁行遮罩尚未确认加载，禁止启动导航'
        state = self.snapshot()
        if not state["digest"]:
            return ""
        if state["state"] == "failed":
            return state["message"]
        if not state["localized"]:
            if state.get("pose_at") and time.time() - state["pose_at"] > 4:
                return "AMCL 定位观测已超时，请检查雷达与定位服务"
            return "请设置小车初始位置并等待 AMCL 定位收敛"
        if time.time() - (state.get("pose_at") or 0) > 4:
            return "AMCL 定位观测已超时，请检查雷达与定位服务"
        return ""

    def request_update(self):
        from std_srvs.srv import Empty
        if not self.state.get("initial_pose_at") or not self.state.get("digest"):
            return
        client = self.node.localization_update_client
        previous = getattr(self, "update_future", None)
        if client.service_is_ready() and (previous is None or previous.done()):
            self.update_future = client.call_async(Empty.Request())

    def snapshot(self):
        with self.lock:
            if self.process is not None and self.process.poll() is not None:
                self.state.update(state="failed", localized=False, message="定位导航进程已退出，请重新加载地图")
            result = {**copy.deepcopy(self.state), "control_session_id": getattr(getattr(self.node, "map_snapshot", None), "session_id", None)}
            result.update(map_features=['keepout-v1'], robot_radius_m=getattr(self.node,'navigation_radius',.25),
                          keepout_required=self.expected_keepout is not None, keepout_ready=self.expected_keepout is None or (self.keepout_received and self.keepout_info_received))
            if result['keepout_required'] and not result['keepout_ready']:
                result.update(localized=False, message='等待禁行遮罩与过滤器信息匹配，暂不可导航')
            if result.get("localized") and time.time() - (result.get("pose_at") or 0) > 4:
                result.update(localized=False, state="localizing", message="AMCL 定位观测已超时，请检查雷达与定位服务")
            return result

    def observe_keepout(self, msg):
        expected = self.expected_keepout
        if expected is None: return
        info = expected['info']
        self.keepout_received = (msg.header.frame_id == 'map' and msg.info.width == info['width'] and msg.info.height == info['height']
            and abs(msg.info.resolution-info['resolution'])<1e-7 and list(msg.data)==expected['data']
            and abs(msg.info.origin.position.x-info['origin']['x'])<1e-6 and abs(msg.info.origin.position.y-info['origin']['y'])<1e-6
            and abs(math.atan2(2*msg.info.origin.orientation.w*msg.info.origin.orientation.z,1-2*msg.info.origin.orientation.z**2)-info['origin']['yaw'])<1e-6)

    def observe_keepout_info(self,msg):
        self.keepout_info_received = (msg.type==0 and msg.filter_mask_topic=='/navigation/keepout_mask' and msg.base==0 and msg.multiplier==1)

    def stop(self):
        with self.operation_lock, self.lock:
            if self.process is not None:
                if self.process.poll() is None:
                    os.killpg(self.process.pid, signal.SIGTERM)
                    try:
                        self.process.wait(timeout=5)
                    except subprocess.TimeoutExpired:
                        os.killpg(self.process.pid, signal.SIGKILL)
                        self.process.wait(timeout=3)
                self.process = None
            self.state.update(state="idle", localized=False, digest=None)
