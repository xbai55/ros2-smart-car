#!/usr/bin/env bash
set -eo pipefail

cd "$(dirname "$0")/../ros2_ws"
source /opt/ros/humble/setup.bash
source install/setup.bash
export ROS_DOMAIN_ID="${ROS_DOMAIN_ID:-77}"
ros2 launch smart_car_decision bringup_all.launch.py
