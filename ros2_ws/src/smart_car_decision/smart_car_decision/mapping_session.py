"""Mapping sessions and process lifecycle, without a ROS dependency in tests."""
import copy
import math
import os
import signal
import subprocess
import threading
import time
import uuid
from pathlib import Path

from .map_assets import save_occupancy_snapshot
from .mapping_settings import MappingSettings


def _number(value):
    try:
        result = float(value)
        return result if math.isfinite(result) else None
    except (TypeError, ValueError, OverflowError):
        return None


def _object(value):
    return value if isinstance(value, dict) else {}


class MapSnapshotStore:
    def __init__(self):
        self._lock = threading.RLock()
        self._snapshot = None
        self.session_id = uuid.uuid4().hex
        self._minimum_stamp = None
        self._last_stamp = None
        self._revision = 0
        self._asset = None

    def begin_session(self, session_id, minimum_stamp):
        with self._lock:
            self.session_id = session_id
            self._minimum_stamp = minimum_stamp
            self._last_stamp = None
            self._snapshot = None
            self._revision = 0
            self._asset = None

    def expect_asset(self, snapshot, digest):
        with self._lock:
            self._asset = (copy.deepcopy(snapshot), digest)

    def update(self, msg):
        with self._lock:
            stamp = int(msg.header.stamp.sec) * 1_000_000_000 + int(msg.header.stamp.nanosec)
            if self._minimum_stamp is not None and stamp < self._minimum_stamp:
                return False
            if self._last_stamp is not None and stamp < self._last_stamp:
                return False
            width, height = int(msg.info.width), int(msg.info.height)
            resolution = _number(msg.info.resolution)
            # Bound allocations before copying the ROS sequence (up to 200 m square at 5 cm).
            if width <= 0 or height <= 0 or width > 16384 or height > 16384 or width * height > 16_000_000:
                return False
            if resolution is None or resolution <= 0 or len(msg.data) != width * height:
                return False
            position, q = msg.info.origin.position, msg.info.origin.orientation
            values = [_number(value) for value in (position.x, position.y, q.x, q.y, q.z, q.w)]
            if any(value is None for value in values) or not str(msg.header.frame_id):
                return False
            data = list(msg.data)
            if any(not isinstance(value, int) or not -1 <= value <= 100 for value in data):
                return False
            # An all-unknown image is not a usable first map.
            if not any(0 <= value <= 100 for value in data):
                return False
            if self._asset:
                expected, digest = self._asset
                info = expected["info"]
                expected_data = [-1 if v < 0 or 25 <= v < 65 else 100 if v >= 65 else 0 for v in expected["data"]]
                if (width != info["width"] or height != info["height"] or
                        str(msg.header.frame_id) != expected["header"]["frame_id"] or
                        abs(resolution - info["resolution"]) > 1e-7 or data != expected_data):
                    return False
            x, y, qx, qy, qz, qw = values
            yaw = math.atan2(2 * (qw * qz + qx * qy), 1 - 2 * (qy * qy + qz * qz))
            if not math.isfinite(yaw):
                return False
            self._revision += 1
            self._last_stamp = stamp
            self._snapshot = {
                "header": {"frame_id": str(msg.header.frame_id), "stamp": {"sec": int(msg.header.stamp.sec), "nanosec": int(msg.header.stamp.nanosec)}},
                "info": {"width": width, "height": height, "resolution": resolution,
                         "origin": {"x": x, "y": y, "yaw": yaw}},
                "data": data, "updated_at": time.time(),
                "session_id": self.session_id, "revision": self._revision,
            }
            if self._asset:
                expected_origin = self._asset[0]["info"]["origin"]
                if any(abs(self._snapshot["info"]["origin"][k] - expected_origin[k]) > 1e-6 for k in ("x", "y", "yaw")):
                    self._snapshot = None
                    return False
                self._snapshot["asset_digest"] = self._asset[1]
                for key in ('keepout','map_features'):
                    if key in self._asset[0]:
                        self._snapshot[key] = copy.deepcopy(self._asset[0][key])
            return True

    def snapshot(self):
        with self._lock:
            return copy.deepcopy(self._snapshot)

    def is_fresh(self, now, timeout=1.5):
        with self._lock:
            return self._snapshot is not None and 0 <= now - self._snapshot["updated_at"] <= timeout

    def clear(self):
        with self._lock:
            self._snapshot = None

    def save(self, directory="/home/jetson/ros2-smart-car/maps", include_snapshot=False):
        snapshot = self.snapshot()
        if snapshot is None:
            raise RuntimeError("map is not available")
        result = save_occupancy_snapshot(snapshot, directory)
        if include_snapshot:
            result["snapshot"] = snapshot
        return result


def slam_process_ids(proc_root=Path("/proc")):
    """Match actual executables, never arbitrary command-line substrings."""
    result = []
    for entry in proc_root.iterdir():
        if not entry.name.isdigit():
            continue
        try:
            executable = Path(os.readlink(entry / "exe").removesuffix(" (deleted)"))
            if executable.name in {"async_slam_toolbox_node", "sync_slam_toolbox_node"}:
                result.append(int(entry.name))
        except (OSError, ValueError):
            continue
    return result


class MappingRestartManager:
    def __init__(self, logger, map_snapshot, *, ros_now_ns=None, settings=None, recorder=None, capture_initial_inputs=None):
        self._logger = logger
        self.settings = settings or MappingSettings()
        self.recorder = recorder
        self.capture_initial_inputs = capture_initial_inputs
        self._map_snapshot = map_snapshot
        self._ros_now_ns = ros_now_ns or (lambda: time.time_ns())
        self._lock = threading.RLock()
        self._process = None
        self._closed = False
        self._frozen = False
        self._status_received_at = None
        self._status = {}
        self._started_monotonic = None
        self._ready_after_wall = None
        self._state = {"session_id": map_snapshot.session_id, "state": "idle", "started_at": None, "error": None}
        self._log_file = Path("/tmp/smart_car_slam_restart.log")

    def restart(self):
        with self._lock:
            if self._closed:
                raise RuntimeError("Web 节点正在关闭，无法重新建图")
            self._frozen = False
            self._state = {"session_id": uuid.uuid4().hex, "state": "starting", "started_at": time.time(), "error": None}
            self._started_monotonic = time.monotonic()
            self._map_snapshot.begin_session(self._state["session_id"], self._ros_now_ns())
            try:
                self._stop_existing_slam()
                active_settings = self.settings.snapshot()
                self._state["max_laser_range"] = active_settings["max_laser_range"]
                if self.recorder:
                    self.recorder.start(self._state["session_id"], active_settings)
                    self._log_file = self.recorder.directory / "slam.log"
                    if self.capture_initial_inputs:
                        self.capture_initial_inputs()
                self._map_snapshot.begin_session(self._state["session_id"], self._ros_now_ns())
                self._ready_after_wall = time.time()
                self._status_received_at = None
                self._status = {}
                self._process = self._start_slam()
                if self._process.poll() is not None:
                    raise RuntimeError(f"SLAM 启动失败（退出码 {self._process.returncode}）{self._log_tail()}")
                self._state["state"] = "waiting_map"
            except (RuntimeError, OSError, subprocess.SubprocessError) as exc:
                if self.recorder:
                    self.recorder.stop("slam_start_failed", error=str(exc))
                self._state.update(state="error", error=str(exc))
                self._logger.error(str(exc))
                raise RuntimeError(str(exc)) from exc
            return {"ok": True, "pid": self._process.pid, "message": "slam_toolbox restarted",
                    "session_id": self._state["session_id"], "mapping": dict(self._state)}

    def stop_mapping(self):
        """End mapping while retaining the last accepted grid for saving."""
        with self._lock:
            # Reject queued SLAM messages as well as future publications.
            self._frozen = True
            self._state.update(state="idle", error=None)
            try:
                self._stop_existing_slam()
            except (OSError, RuntimeError, subprocess.SubprocessError) as exc:
                self._state.update(state="error", error=str(exc))
                raise
            finally:
                if self.recorder:
                    self.recorder.stop("mode_exit")

    def stop_for_navigation(self):
        with self._lock:
            if self.recorder:
                self.recorder.stop("navigation")
            self._stop_existing_slam()
            self._frozen = False
            session = uuid.uuid4().hex
            self._map_snapshot.begin_session(session, None)
            self._state = {"session_id": session, "state": "idle", "started_at": None, "error": None}

    def observe_status(self, snapshot):
        with self._lock:
            self._status = copy.deepcopy(_object(snapshot))
            if self.recorder:
                self.recorder.append_status(self._status)
            self._status_received_at = time.monotonic()
            self._refresh_state()

    def on_map(self, msg):
        with self._lock:
            if self._frozen or self._state["state"] == "starting":
                return False
            accepted = self._map_snapshot.update(msg)
            self._refresh_state()
            return accepted

    def snapshot(self):
        with self._lock:
            self._refresh_state()
            result = dict(self._state)
            result["configured_max_laser_range"] = self.settings.snapshot()["max_laser_range"]
            if self.recorder:
                result["recording"] = self.recorder.snapshot()
            return result

    def _missing_inputs(self):
        missing = []
        now = time.monotonic()
        if not self._map_snapshot.is_fresh(time.time()):
            missing.append("有效首张地图")
        if self._status_received_at is None or now - self._status_received_at > 1.5:
            missing.append("实时状态")
            return missing
        for name, age_key in (("lidar", "scan_age_sec"), ("odom", "odom_age_sec"), ("map_pose", "age_sec")):
            value = _object(self._status.get(name))
            age = _number(value.get(age_key))
            if not value.get("ok") or age is None or not 0 <= age <= 1.5:
                missing.append(name)
        tf = _object(self._status.get("tf"))
        checked = _number(tf.get("checked_at"))
        tf_age = _number(tf.get("age_sec"))
        # Older duck-typed callers omit age_sec; a present invalid age is never accepted.
        stale_tf = "age_sec" in tf and (tf_age is None or not 0 <= tf_age <= 1.5)
        if not tf.get("ok") or stale_tf or checked is None or not 0 <= time.time() - checked <= 1.5:
            missing.append("tf")
        pose = _object(self._status.get("map_pose"))
        # A cached map->base transform from the previous session must not declare readiness.
        started = self._ready_after_wall
        pose_updated, pose_age = _number(pose.get("updated_at")), _number(pose.get("age_sec"))
        if started is not None and (pose_updated is None or pose_age is None or pose_updated - pose_age < started):
            if "map_pose" not in missing:
                missing.append("本轮地图定位")
        return missing

    def _refresh_state(self):
        if self._closed or self._frozen:
            return
        if self._state["state"] in {"starting", "error"}:
            return
        if self.recorder:
            recording = self.recorder.snapshot()
            if self._state["state"] in {"waiting_map", "ready"} and recording["state"] == "error":
                self._state.update(state="error", error=recording["error"])
                return
        if self._process is not None and self._process.poll() is not None:
            if self.recorder:
                self.recorder.stop("slam_exited", error="SLAM 进程意外退出")
            self._state.update(state="error", error=f"SLAM 进程退出（退出码 {self._process.returncode}）{self._log_tail()}")
            return
        missing = self._missing_inputs()
        if not missing:
            self._state.update(state="ready", error=None)
        elif self._state["state"] == "waiting_map" and self._started_monotonic is not None and time.monotonic() - self._started_monotonic >= 15:
            self._state.update(state="error", error=f"建图启动超过 15 秒，缺少：{', '.join(missing)}{self._log_tail()}")

    def _log_tail(self):
        try:
            with self._log_file.open("rb") as handle:
                handle.seek(max(0, self._log_file.stat().st_size - 2000))
                return "；日志：" + handle.read().decode("utf-8", errors="replace")[-1200:]
        except OSError:
            return ""

    def close(self):
        """Reap only this manager's detached launch group during Web shutdown."""
        with self._lock:
            self._closed = True
            self._stop_owned_slam()
            if self.recorder:
                self.recorder.stop("shutdown")
            self._state.update(state="idle", error=None)

    def _stop_owned_slam(self):
        process = self._process
        if process is None:
            return
        if process.poll() is None:
            # Only this manager's isolated launch group is terminated as a group.
            try:
                os.killpg(process.pid, signal.SIGTERM)
            except ProcessLookupError:
                pass
            try:
                process.wait(timeout=3)
            except subprocess.TimeoutExpired:
                try:
                    os.killpg(process.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
                process.wait(timeout=3)
        else:
            process.wait(timeout=3)
        self._process = None

    def _stop_existing_slam(self):
        self._stop_owned_slam()
        pids = slam_process_ids()
        for pid in pids:
            try:
                os.kill(pid, signal.SIGTERM)
            except ProcessLookupError:
                pass
        deadline = time.monotonic() + 3
        while slam_process_ids():
            if time.monotonic() >= deadline:
                break
            time.sleep(.05)
        remaining = slam_process_ids()
        for pid in remaining:
            try:
                os.kill(pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
        deadline = time.monotonic() + 2
        while slam_process_ids():
            if time.monotonic() >= deadline:
                raise RuntimeError("旧 SLAM 进程未退出，取消重新建图")
            time.sleep(.05)

    def _start_slam(self):
        from ament_index_python.packages import get_package_share_directory
        import yaml
        source = Path(get_package_share_directory("smart_car_decision")) / "config" / "slam_toolbox.yaml"
        directory = self.recorder.directory if self.recorder else Path("/tmp/smart_car_mapping") / self._state["session_id"]
        directory.mkdir(parents=True, exist_ok=True)
        params_file = directory / "slam-params.yaml"
        parameters = yaml.safe_load(source.read_text(encoding="utf-8"))
        parameters["slam_toolbox"]["ros__parameters"]["max_laser_range"] = self._state["max_laser_range"]
        params_file.write_text(yaml.safe_dump(parameters, allow_unicode=True), encoding="utf-8")
        # Truncate per launch so diagnostics do not include a previous session's errors.
        with self._log_file.open("wb", buffering=0) as log_handle:
            process = subprocess.Popen(["ros2", "launch", "slam_toolbox", "online_async_launch.py",
                                        f"slam_params_file:={params_file}", "use_sim_time:=false"],
                                       stdout=log_handle, stderr=subprocess.STDOUT,
                                       env=os.environ.copy(), start_new_session=True)
        self._logger.info(f"Restarted slam_toolbox via web API, pid={process.pid}")
        return process
