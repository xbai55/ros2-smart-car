#!/usr/bin/env bash
set -eo pipefail

cd "$(dirname "$0")/../ros2_ws"
source /opt/ros/humble/setup.bash

for setup_file in \
  "$HOME/yahboomcar_ros2_ws/yahboomcar_ws/install/setup.bash" \
  "$HOME/yahboomcar_ros2_ws/software/library_ws/install/setup.bash" \
  "$HOME/yahboomcar_ros2_ws_yahboomcar_ws/yahboomcar_ros2_ws/yahboomcar_ws/install/setup.bash"
do
  if [ -f "$setup_file" ]; then
    # Source Yahboom's workspace so bringup_all can start the chassis driver.
    source "$setup_file"
  fi
done

source install/setup.bash
export ROS_DOMAIN_ID="${ROS_DOMAIN_ID:-77}"
ros2 launch smart_car_decision bringup_all.launch.py
