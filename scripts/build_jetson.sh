#!/usr/bin/env bash
set -eo pipefail

cd "$(dirname "$0")/../ros2_ws"
source /opt/ros/humble/setup.bash
pip3 install -r src/smart_car_decision/requirements-web.txt
pip3 install -r src/smart_car_decision/requirements-vision.txt
colcon build --packages-select smart_car_decision
