#!/usr/bin/env bash
set -eo pipefail

SMART_CAR_REQUIRE_LIDAR="${SMART_CAR_REQUIRE_LIDAR:-1}"
SMART_CAR_REQUIRE_CAMERA="${SMART_CAR_REQUIRE_CAMERA:-1}"
SMART_CAR_LIDAR_PORT="${SMART_CAR_LIDAR_PORT:-/dev/rplidar}"
SMART_CAR_CAMERA_SOURCE="${SMART_CAR_CAMERA_SOURCE:-0}"
SMART_CAR_START_LIDAR_DRIVER="${SMART_CAR_START_LIDAR_DRIVER:-1}"
SMART_CAR_START_YOLO_CAMERA="${SMART_CAR_START_YOLO_CAMERA:-1}"
SMART_CAR_START_COLOR_TRACKER="${SMART_CAR_START_COLOR_TRACKER:-1}"
SMART_CAR_START_WEB_CAMERA="${SMART_CAR_START_WEB_CAMERA:-1}"

if [ "${SMART_CAR_STOP_VENDOR_ROSMASTER:-1}" = "1" ]; then
  if pgrep -f "/home/jetson/Rosmaster/rosmaster/rosmaster_main.py" >/dev/null; then
    pids="$(pgrep -f "/home/jetson/Rosmaster/rosmaster/rosmaster_main.py" | tr '\n' ' ')"
    echo "Stopping vendor rosmaster processes: ${pids}"
    kill ${pids} 2>/dev/null || true
    sleep 2
    pkill -9 -f "/home/jetson/Rosmaster/rosmaster/rosmaster_main.py" 2>/dev/null || true
  fi
fi

print_runtime_diagnostics() {
  echo "== Runtime identity =="
  id || true
  groups || true
  echo "== Runtime device nodes =="
  ls -l /dev/rplidar /dev/myserial /dev/ttyUSB* /dev/video* 2>/dev/null || true
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

camera_device_exists() {
  if [[ "$SMART_CAR_CAMERA_SOURCE" =~ ^[0-9]+$ ]]; then
    [ -e "/dev/video${SMART_CAR_CAMERA_SOURCE}" ]
    return
  fi
  [ -e "$SMART_CAR_CAMERA_SOURCE" ] || compgen -G "/dev/video*" >/dev/null
}

detect_camera_source() {
  if camera_device_exists; then
    echo "$SMART_CAR_CAMERA_SOURCE"
    return 0
  fi
  for device in /dev/video*; do
    [ -e "$device" ] || continue
    echo "${device#/dev/video}"
    return 0
  done
  return 1
}

print_runtime_diagnostics

if [ ! -e /dev/myserial ] && [ ! -e /dev/ttyUSB0 ]; then
  echo "ERROR: base serial device is missing in container; expected /dev/myserial or /dev/ttyUSB0" >&2
  exit 1
fi

if [ "$SMART_CAR_START_LIDAR_DRIVER" = "1" ]; then
  if SMART_CAR_LIDAR_PORT="$(detect_lidar_port)"; then
    export SMART_CAR_LIDAR_PORT
  elif [ "$SMART_CAR_REQUIRE_LIDAR" = "1" ]; then
    echo "ERROR: lidar device is missing in container; set SMART_CAR_LIDAR_PORT or restore /dev/rplidar" >&2
    exit 1
  else
    echo "WARN: lidar missing; disabling lidar driver because SMART_CAR_REQUIRE_LIDAR=0" >&2
    SMART_CAR_START_LIDAR_DRIVER=0
  fi
fi

if SMART_CAR_CAMERA_SOURCE="$(detect_camera_source)"; then
  export SMART_CAR_CAMERA_SOURCE
else
  if [ "$SMART_CAR_REQUIRE_CAMERA" = "1" ]; then
    echo "ERROR: camera device is missing in container; expected /dev/video${SMART_CAR_CAMERA_SOURCE} or /dev/video*" >&2
    exit 1
  fi
  echo "WARN: camera missing; disabling camera nodes because SMART_CAR_REQUIRE_CAMERA=0" >&2
  SMART_CAR_START_YOLO_CAMERA=0
  SMART_CAR_START_COLOR_TRACKER=0
  SMART_CAR_START_WEB_CAMERA=0
fi

export SMART_CAR_LIDAR_PORT
export SMART_CAR_CAMERA_SOURCE

echo "Starting smart-car ROS2 runtime: lidar_port=${SMART_CAR_LIDAR_PORT:-disabled} camera_source=${SMART_CAR_CAMERA_SOURCE:-disabled} start_lidar=${SMART_CAR_START_LIDAR_DRIVER} start_yolo=${SMART_CAR_START_YOLO_CAMERA} start_color=${SMART_CAR_START_COLOR_TRACKER} start_web_camera=${SMART_CAR_START_WEB_CAMERA}"

exec ros2 launch smart_car_decision bringup_all.launch.py \
  lidar_serial_port:="${SMART_CAR_LIDAR_PORT:-/dev/rplidar}" \
  camera_source:="${SMART_CAR_CAMERA_SOURCE:-0}" \
  start_lidar_driver:="${SMART_CAR_START_LIDAR_DRIVER}" \
  start_yolo_camera:="${SMART_CAR_START_YOLO_CAMERA}" \
  start_color_tracker:="${SMART_CAR_START_COLOR_TRACKER}" \
  start_web_camera:="${SMART_CAR_START_WEB_CAMERA}"
