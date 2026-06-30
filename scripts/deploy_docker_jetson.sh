#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")/.."

compose_file="docker-compose.jetson.yml"
SMART_CAR_REQUIRE_LIDAR="${SMART_CAR_REQUIRE_LIDAR:-1}"
SMART_CAR_REQUIRE_CAMERA="${SMART_CAR_REQUIRE_CAMERA:-1}"
SMART_CAR_USB_SETTLE_SEC="${SMART_CAR_USB_SETTLE_SEC:-4}"
SMART_CAR_LIDAR_PORT="${SMART_CAR_LIDAR_PORT:-}"
SMART_CAR_CAMERA_SOURCE="${SMART_CAR_CAMERA_SOURCE:-}"

export SMART_CAR_REQUIRE_LIDAR
export SMART_CAR_REQUIRE_CAMERA
export SMART_CAR_LIDAR_PORT
export SMART_CAR_CAMERA_SOURCE

if ! command -v docker >/dev/null 2>&1; then
  echo "ERROR: docker is not installed or not in PATH" >&2
  exit 1
fi

if docker compose version >/dev/null 2>&1; then
  compose=(docker compose)
elif command -v docker-compose >/dev/null 2>&1; then
  compose=(docker-compose)
else
  echo "ERROR: Docker Compose is not available" >&2
  exit 1
fi

print_device_diagnostics() {
  echo "== USB devices =="
  lsusb || true
  echo "== Device nodes =="
  ls -l /dev/myserial /dev/rplidar /dev/ttyUSB* /dev/video* 2>/dev/null || true
  echo "== Recent USB kernel log =="
  (sudo -n dmesg 2>/dev/null || dmesg 2>/dev/null || true) \
    | tail -n 160 \
    | egrep -i 'usb|ttyUSB|cp210|ch34|uvc|video|camera|lidar|serial|disconnect|reset|error' || true
}

stop_device_conflicts() {
  echo "Stopping older native smart-car and device owner processes..."
  python3 - <<'PY'
import os
import signal
import subprocess
import time

patterns = [
    "smart_car_decision",
    "bringup_all.launch.py",
    "web_app_node",
    "system_status_node",
    "decision_controller",
    "tcp_command_bridge",
    "laser_obstacle_monitor",
    "yolo11_camera_node",
    "color_tracker_node",
    "object_follow_node",
    "mode_manager",
    "slam_toolbox",
    "sllidar_node",
    "sllidar_driver",
    "yahboom_base_driver",
    "base_node_X3",
    "robot_state_publisher",
    "static_transform_publisher",
    "rosmaster_main.py",
    "/home/jetson/Rosmaster/rosmaster",
]
devices = ["/dev/video0", "/dev/video1", "/dev/ttyUSB0", "/dev/ttyUSB1", "/dev/rplidar", "/dev/myserial"]
self_pid = os.getpid()
pids = {}

out = subprocess.check_output(["ps", "-eo", "pid,ppid,cmd"], text=True, errors="replace")
for line in out.splitlines()[1:]:
    parts = line.strip().split(None, 2)
    if len(parts) < 3:
        continue
    pid = int(parts[0])
    cmd = parts[2]
    if pid == self_pid or "deploy_docker_jetson.sh" in cmd:
        continue
    if any(pattern in cmd for pattern in patterns):
        pids[pid] = cmd

for device in devices:
    if not os.path.exists(device):
        continue
    try:
        fuser = subprocess.check_output(["fuser", device], text=True, stderr=subprocess.DEVNULL)
    except subprocess.CalledProcessError:
        continue
    for token in fuser.split():
        try:
            pid = int(token)
        except ValueError:
            continue
        if pid != self_pid:
            pids.setdefault(pid, f"device owner of {device}")

for pid, cmd in sorted(pids.items()):
    print(f"TERM {pid} {cmd[:160]}")
    try:
        os.kill(pid, signal.SIGTERM)
    except ProcessLookupError:
        pass

time.sleep(2)

for pid, cmd in sorted(pids.items()):
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        continue
    print(f"KILL {pid} {cmd[:160]}")
    try:
        os.kill(pid, signal.SIGKILL)
    except ProcessLookupError:
        pass

print(f"stopped_candidates={len(pids)}")
PY
}

recover_hardware() {
  echo "Recovering USB serial and camera devices..."
  sudo modprobe cp210x || true
  sudo modprobe uvcvideo || true
  sudo udevadm control --reload-rules || true
  sudo udevadm trigger || true
  sleep "$SMART_CAR_USB_SETTLE_SEC"
}

detect_lidar_port() {
  if [ -n "${SMART_CAR_LIDAR_PORT:-}" ] && [ -e "$SMART_CAR_LIDAR_PORT" ]; then
    echo "$SMART_CAR_LIDAR_PORT"
    return 0
  fi
  if [ -e /dev/rplidar ]; then
    echo /dev/rplidar
    return 0
  fi
  for device in /dev/ttyUSB*; do
    [ -e "$device" ] || continue
    if udevadm info -q property -n "$device" 2>/dev/null | grep -Eq 'ID_VENDOR_ID=10c4|ID_MODEL_ID=ea60|ID_USB_DRIVER=cp210x'; then
      echo "$device"
      return 0
    fi
  done
  return 1
}

detect_camera_source() {
  if [ -n "${SMART_CAR_CAMERA_SOURCE:-}" ]; then
    if [[ "$SMART_CAR_CAMERA_SOURCE" =~ ^[0-9]+$ ]] && [ -e "/dev/video${SMART_CAR_CAMERA_SOURCE}" ]; then
      echo "$SMART_CAR_CAMERA_SOURCE"
      return 0
    fi
    if [ -e "$SMART_CAR_CAMERA_SOURCE" ]; then
      echo "$SMART_CAR_CAMERA_SOURCE"
      return 0
    fi
  fi
  if [ -e /dev/video0 ]; then
    echo "0"
    return 0
  fi
  for device in /dev/video*; do
    [ -e "$device" ] || continue
    echo "${device#/dev/video}"
    return 0
  done
  return 1
}

check_hardware() {
  local failed=0
  echo "Checking smart-car hardware devices..."

  if [ -e /dev/myserial ]; then
    SMART_CAR_BASE_PORT=/dev/myserial
  elif [ -e /dev/ttyUSB0 ]; then
    SMART_CAR_BASE_PORT=/dev/ttyUSB0
  else
    echo "ERROR: base serial device is missing; expected /dev/myserial or /dev/ttyUSB0" >&2
    failed=1
  fi

  if SMART_CAR_LIDAR_PORT="$(detect_lidar_port)"; then
    export SMART_CAR_LIDAR_PORT
  elif [ "$SMART_CAR_REQUIRE_LIDAR" = "1" ]; then
    echo "ERROR: lidar device is missing; expected /dev/rplidar or a CP210x /dev/ttyUSB* device" >&2
    failed=1
  else
    echo "WARN: lidar device is missing; continuing because SMART_CAR_REQUIRE_LIDAR=0" >&2
    export SMART_CAR_START_LIDAR_DRIVER=0
  fi

  if SMART_CAR_CAMERA_SOURCE="$(detect_camera_source)"; then
    export SMART_CAR_CAMERA_SOURCE
    export SMART_CAR_START_YOLO_CAMERA="${SMART_CAR_START_YOLO_CAMERA:-1}"
    export SMART_CAR_START_COLOR_TRACKER="${SMART_CAR_START_COLOR_TRACKER:-1}"
    export SMART_CAR_START_WEB_CAMERA="${SMART_CAR_START_WEB_CAMERA:-1}"
  elif [ "$SMART_CAR_REQUIRE_CAMERA" = "1" ]; then
    echo "ERROR: camera device is missing; expected /dev/video0 or another /dev/video* device" >&2
    failed=1
  else
    echo "WARN: camera device is missing; disabling camera nodes because SMART_CAR_REQUIRE_CAMERA=0" >&2
    export SMART_CAR_START_YOLO_CAMERA=0
    export SMART_CAR_START_COLOR_TRACKER=0
    export SMART_CAR_START_WEB_CAMERA=0
  fi

  if [ "$failed" -ne 0 ]; then
    print_device_diagnostics >&2
    exit 1
  fi

  echo "Hardware selection: base=${SMART_CAR_BASE_PORT:-missing} lidar=${SMART_CAR_LIDAR_PORT:-disabled} camera=${SMART_CAR_CAMERA_SOURCE:-disabled}"
}

mkdir -p maps debug_logs web-console/dist

if ! docker image inspect "${SMART_CAR_BASE_IMAGE:-docker.m.daocloud.io/library/ros:humble-ros-base}" >/dev/null 2>&1; then
  echo "Pulling ROS2 Humble base image from mirror..."
  docker pull "${SMART_CAR_BASE_IMAGE:-docker.m.daocloud.io/library/ros:humble-ros-base}"
fi

echo "Stopping older Docker runtime..."
"${compose[@]}" -f "$compose_file" down --remove-orphans || true

stop_device_conflicts
recover_hardware
check_hardware

echo "Building and starting smart-car-runtime..."
"${compose[@]}" -f "$compose_file" build smart-car-runtime
"${compose[@]}" -f "$compose_file" up -d smart-car-runtime

echo "Waiting for /api/status..."
for _ in $(seq 1 40); do
  if curl -fsS --max-time 2 http://127.0.0.1:8080/api/status >/tmp/smart-car-status.json; then
    break
  fi
  sleep 1
done

bash scripts/healthcheck_docker.sh
