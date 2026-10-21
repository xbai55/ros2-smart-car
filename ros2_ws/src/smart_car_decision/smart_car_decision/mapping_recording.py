"""Per-session full ROS input recording, with readable status and event logs."""
import json
import os
import shutil
import signal
import subprocess
import threading
import time
import yaml
from pathlib import Path

INPUT_TOPICS = (
    "/scan", "/odom_raw", "/odom", "/imu/data_raw", "/imu/data", "/tf", "/tf_static",
    "/cmd_vel", "/manual_cmd", "/robot/mode", "/robot/speed_scale", "/robot/turn_speed",
    "/robot/status", "/map", "/parameter_events",
)
INITIAL_CONTROL_TOPICS = ("/manual_cmd", "/robot/mode", "/robot/speed_scale", "/robot/turn_speed")


class MappingInputRecorder:
    def __init__(self, root="~/.ros/insightrover/mapping_logs"):
        self.root = Path(root).expanduser()
        self.directory = None
        self._process = None
        self._lock = threading.RLock()
        self._state = {"state": "idle", "error": None, "directory": None}
        self._last_disk_check = 0.

    def _write_summary(self):
        if self.directory:
            temporary = self.directory / "session.json.tmp"
            temporary.write_text(json.dumps(self._state, ensure_ascii=False, indent=2), encoding="utf-8")
            os.replace(temporary, self.directory / "session.json")

    def event(self, kind, **data):
        with self._lock:
            if self.directory:
                with (self.directory / "events.jsonl").open("a", encoding="utf-8") as handle:
                    handle.write(json.dumps({"time": time.time(), "event": kind, **data}, ensure_ascii=False, allow_nan=False) + "\n")

    def append_status(self, status):
        with self._lock:
            if self._state["state"] == "recording":
                with (self.directory / "status.jsonl").open("a", encoding="utf-8") as handle:
                    handle.write(json.dumps({"logged_at": time.time(), **status}, ensure_ascii=False) + "\n")

    def start(self, session_id, settings):
        with self._lock:
            self.stop("next_session")
            if not session_id.isalnum():
                raise ValueError("invalid session id")
            self.root.mkdir(parents=True, exist_ok=True)
            if shutil.disk_usage(self.root).free < 512 * 1024 * 1024:
                raise RuntimeError("日志空间不足 512 MB，无法记录完整建图输入")
            directory = self.root / (time.strftime("%Y%m%d_%H%M%S") + "_" + session_id)
            directory.mkdir()
            self.directory = directory
            self._state = {"state": "starting", "error": None, "directory": str(directory),
                           "session_id": session_id, "started_at": time.time(), "ended_at": None,
                           "settings": dict(settings), "requested_topics": list(INPUT_TOPICS),
                           "complete": False}
            qos = directory / "qos.yaml"
            qos.write_text("/tf_static:\n  durability: transient_local\n  reliability: reliable\n  history: keep_all\n"
                           "/robot/turn_speed:\n  durability: transient_local\n  reliability: reliable\n  history: keep_last\n  depth: 1\n", encoding="utf-8")
            self._write_summary()
            self.event("recording_start", settings=settings, topics=list(INPUT_TOPICS))
            try:
                with (directory / "recorder.log").open("wb", buffering=0) as output:
                    self._process = subprocess.Popen(
                        ["ros2", "bag", "record", "--storage", "sqlite3", "--qos-profile-overrides-path", str(qos),
                         "-o", str(directory / "inputs"), *INPUT_TOPICS], stdout=output,
                        stderr=subprocess.STDOUT, env=os.environ.copy(), start_new_session=True)
                deadline = time.monotonic() + 10
                while time.monotonic() < deadline:
                    if self._process.poll() is not None:
                        raise RuntimeError("完整输入记录进程启动失败，请查看 recorder.log")
                    log = (directory / "recorder.log").read_text(encoding="utf-8", errors="replace")
                    # Static TF is latched; require its subscription before starting SLAM.
                    subscriptions = ("/tf_static", "/scan", *INITIAL_CONTROL_TOPICS)
                    if all(f"Subscribed to topic '{topic}'" in log for topic in subscriptions):
                        self._state["state"] = "recording"
                        self._write_summary()
                        return dict(self._state)
                    time.sleep(.05)
                raise RuntimeError("完整输入记录等待雷达、静态 TF 或控制话题超过 10 秒")
            except (OSError, RuntimeError) as exc:
                self.stop("start_failed", error=str(exc))
                self._state.update(state="error", error=str(exc), complete=False)
                self._write_summary()
                raise RuntimeError(str(exc)) from exc

    def snapshot(self):
        with self._lock:
            if self._state["state"] == "recording":
                if self._process.poll() is not None:
                    self.stop("process_exited", error="完整输入记录进程意外退出")
                elif time.monotonic() - self._last_disk_check > 5:
                    self._last_disk_check = time.monotonic()
                    if shutil.disk_usage(self.root).free < 256 * 1024 * 1024:
                        self.stop("disk_full", error="日志剩余空间不足 256 MB，完整输入记录已中断")
            return dict(self._state)

    def stop(self, reason="stopped", error=None):
        with self._lock:
            if self._process is None:
                return
            process, self._process = self._process, None
            try:
                if process.poll() is None:
                    os.killpg(process.pid, signal.SIGINT)
                process.wait(timeout=10)
            except (ProcessLookupError, subprocess.TimeoutExpired):
                error = error or "记录进程未正常收尾，数据可能不完整"
                try:
                    os.killpg(process.pid, signal.SIGTERM)
                    process.wait(timeout=3)
                except (ProcessLookupError, subprocess.TimeoutExpired):
                    error = error or "记录进程无法退出"
                    try:
                        os.killpg(process.pid, getattr(signal, "SIGKILL", 9))
                        process.wait(timeout=3)
                    except (ProcessLookupError, subprocess.TimeoutExpired):
                        pass
            metadata = self.directory / "inputs" / "metadata.yaml"
            complete = error is None and process.returncode in (0, -signal.SIGINT, 130) and metadata.exists()
            if metadata.exists():
                try:
                    information = yaml.safe_load(metadata.read_text(encoding="utf-8"))["rosbag2_bagfile_information"]
                    counts = {row["topic_metadata"]["name"]: row["message_count"]
                              for row in information["topics_with_message_count"]}
                    self._state["topic_counts"] = counts
                    self._state["missing_topics"] = [topic for topic in INPUT_TOPICS if not counts.get(topic)]
                    required = {"/scan", "/odom_raw", "/odom", "/imu/data", "/tf", "/tf_static", "/cmd_vel", "/robot/status", "/map", *INITIAL_CONTROL_TOPICS}
                    missing = sorted(required.intersection(self._state["missing_topics"]))
                    if missing:
                        error = error or "缺少完整输入：" + ", ".join(missing)
                        complete = False
                except (OSError, ValueError, KeyError, TypeError, yaml.YAMLError):
                    complete, error = False, error or "无法读取 rosbag 元数据"
            if not complete and error is None:
                error = "记录未正常完成或缺少 metadata.yaml，请检查 recorder.log"
            self._state.update(state="finished" if complete else "error", complete=complete,
                               error=error, ended_at=time.time(), reason=reason)
            self.event("recording_stop", reason=reason, complete=complete, error=error)
            self._write_summary()
