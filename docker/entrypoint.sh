#!/usr/bin/env bash
set -eo pipefail

source /opt/ros/humble/setup.bash

for setup_file in \
  "/opt/yahboomcar_ros2_ws/yahboomcar_ws/install/setup.bash" \
  "/opt/yahboomcar_ros2_ws/software/library_ws/install/setup.bash" \
  "/opt/yahboomcar_ros2_ws_yahboomcar_ws/yahboomcar_ros2_ws/yahboomcar_ws/install/setup.bash" \
  "$HOME/yahboomcar_ros2_ws/yahboomcar_ws/install/setup.bash" \
  "$HOME/yahboomcar_ros2_ws/software/library_ws/install/setup.bash"
do
  if [ -f "$setup_file" ]; then
    source "$setup_file"
  fi
done

source "${SMART_CAR_ROOT:-/workspace/ros2-smart-car}/ros2_ws/install/setup.bash"

export ROS_DOMAIN_ID="${ROS_DOMAIN_ID:-77}"
export RMW_IMPLEMENTATION="${RMW_IMPLEMENTATION:-rmw_fastrtps_cpp}"

exec "$@"
