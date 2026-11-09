#!/usr/bin/env bash
set -euo pipefail

diagnostics_dir="${VEHICLE_DIAGNOSTICS_DIR:-$HOME/.local/share/insightrover/diagnostics}"
mkdir -p -m 700 "$diagnostics_dir" || printf '%s\n' 'Diagnostic volume unavailable' >&2
docker build -t ros2-smart-car:humble .
docker run --rm -it --network host --privileged \
  -v /dev:/dev \
  -v "$diagnostics_dir:/var/lib/insightrover/diagnostics" \
  -e VEHICLE_DIAGNOSTICS_DIR=/var/lib/insightrover/diagnostics \
  ros2-smart-car:humble
