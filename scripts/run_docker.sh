#!/usr/bin/env bash
set -euo pipefail

docker build -t ros2-smart-car:humble .
docker run --rm -it --network host --privileged \
  -v /dev:/dev \
  ros2-smart-car:humble
