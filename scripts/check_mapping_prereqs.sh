#!/usr/bin/env bash
set -euo pipefail

laser_frame="${LASER_FRAME:-laser}"
failed=0

check_topic() {
  local topic="$1"
  if ros2 topic list | grep -Fxq "$topic" && timeout 5 ros2 topic echo "$topic" --once >/dev/null 2>&1; then
    echo "OK topic: $topic"
  else
    echo "FAIL topic: $topic" >&2
    failed=1
  fi
}

check_tf() {
  local parent="$1"
  local child="$2"
  local output
  output="$(timeout 5 ros2 run tf2_ros tf2_echo "$parent" "$child" 2>&1 || true)"
  if printf '%s' "$output" | grep -q "Translation:"; then
    echo "OK TF: $parent -> $child"
  else
    echo "FAIL TF: $parent -> $child" >&2
    failed=1
  fi
}

check_topic /scan
check_topic /odom
check_tf odom base_link
check_tf base_link "$laser_frame"

if ros2 pkg prefix slam_toolbox >/dev/null 2>&1; then
  echo "OK package: slam_toolbox"
else
  echo "FAIL package: slam_toolbox" >&2
  failed=1
fi

exit "$failed"
