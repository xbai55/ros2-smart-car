#!/usr/bin/env bash
set -euo pipefail

container="${SMART_CAR_CONTAINER:-smart-car-runtime}"
SMART_CAR_REQUIRE_LIDAR="${SMART_CAR_REQUIRE_LIDAR:-1}"
SMART_CAR_REQUIRE_CAMERA="${SMART_CAR_REQUIRE_CAMERA:-1}"

fail() {
  echo "ERROR: $*" >&2
  exit 1
}

if ! docker ps --format '{{.Names}}' | grep -Fxq "$container"; then
  fail "container is not running: $container"
fi

echo "== Docker container =="
docker ps --filter "name=^/${container}$" --format 'table {{.Names}}\t{{.Status}}\t{{.Image}}'

echo "== Listening ports =="
ss -ltnp | egrep ':(8080|9999)\b|State' || true
ss -ltnp | grep -Eq ':8080\b' || fail "web port 8080 is not listening"
ss -ltnp | grep -Eq ':9999\b' || fail "TCP command bridge port 9999 is not listening"

echo "== Web API =="
curl -fsS --max-time 6 http://127.0.0.1:8080/api/status >/tmp/smart-car-status.json || fail "GET /api/status failed"
python3 - <<'PY'
import json
import sys
from pathlib import Path

status = json.loads(Path("/tmp/smart-car-status.json").read_text())
summary = {
    "mode": status.get("mode"),
    "last_command": status.get("last_command"),
}
for key in ("lidar", "odom", "tf", "map", "cmd_vel"):
    value = status.get(key)
    if isinstance(value, dict):
        summary[f"{key}.ok"] = value.get("ok")
print(summary)
if not status.get("odom", {}).get("ok"):
    print("ERROR: /api/status reports odom unhealthy", file=sys.stderr)
    sys.exit(2)
if not status.get("cmd_vel", {}).get("ok"):
    print("ERROR: /api/status reports cmd_vel unhealthy", file=sys.stderr)
    sys.exit(3)
PY

echo "== ROS2 graph =="
docker exec "$container" bash -lc '
set -e
source /opt/ros/humble/setup.bash
source /workspace/ros2-smart-car/ros2_ws/install/setup.bash
export ROS_DOMAIN_ID="${ROS_DOMAIN_ID:-77}"
timeout 8 ros2 node list
timeout 8 ros2 topic list
' || fail "failed to query ROS2 graph inside container"

nodes="$(docker exec "$container" bash -lc '
source /opt/ros/humble/setup.bash
source /workspace/ros2-smart-car/ros2_ws/install/setup.bash
export ROS_DOMAIN_ID="${ROS_DOMAIN_ID:-77}"
timeout 8 ros2 node list
')"
for node in /base_node /system_status_node /tcp_command_bridge /web_app_node; do
  echo "$nodes" | grep -Fxq "$node" || fail "required ROS2 node is missing: $node"
done

echo "== Required topics =="
docker exec "$container" bash -lc '
set -e
source /opt/ros/humble/setup.bash
source /workspace/ros2-smart-car/ros2_ws/install/setup.bash
export ROS_DOMAIN_ID="${ROS_DOMAIN_ID:-77}"
for topic in /odom /robot/status; do
  echo "--- $topic sample ---"
  timeout 8 ros2 topic echo --once "$topic" >/dev/null
done
'

if [ "$SMART_CAR_REQUIRE_LIDAR" = "1" ]; then
  docker exec "$container" bash -lc '
  set -e
  source /opt/ros/humble/setup.bash
  source /workspace/ros2-smart-car/ros2_ws/install/setup.bash
  export ROS_DOMAIN_ID="${ROS_DOMAIN_ID:-77}"
  ros2 topic list | grep -Fxq /scan
  timeout 8 ros2 topic echo --once /scan >/dev/null
  ' || fail "required lidar topic /scan is missing or has no data"
else
  echo "WARN: skipping /scan data check because SMART_CAR_REQUIRE_LIDAR=0"
fi

echo "== Camera capability =="
docker exec "$container" bash -lc 'ls -l /dev/video* 2>/dev/null || true'
topics="$(docker exec "$container" bash -lc '
source /opt/ros/humble/setup.bash
source /workspace/ros2-smart-car/ros2_ws/install/setup.bash
export ROS_DOMAIN_ID="${ROS_DOMAIN_ID:-77}"
timeout 8 ros2 topic list
')"
if [ "$SMART_CAR_REQUIRE_CAMERA" = "1" ]; then
  docker exec "$container" bash -lc 'compgen -G "/dev/video*" >/dev/null' || fail "required camera device /dev/video* is missing"
  echo "$topics" | grep -Fxq /vision/annotated_frame || fail "camera topic /vision/annotated_frame is missing"
  echo "$nodes" | grep -Eq '^/(yolo11_camera_node|color_tracker_node)$' || fail "camera processing node is missing"
else
  echo "WARN: skipping strict camera checks because SMART_CAR_REQUIRE_CAMERA=0"
fi

echo "Docker smart-car runtime healthcheck passed."
