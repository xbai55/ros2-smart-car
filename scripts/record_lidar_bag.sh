#!/usr/bin/env bash
set -euo pipefail

output="${1:-bags/lidar_$(date +%Y%m%d_%H%M%S)}"
mkdir -p "$(dirname "$output")"

echo "Recording lidar mapping inputs to: $output"
exec ros2 bag record -o "$output" /scan /odom /tf /tf_static
