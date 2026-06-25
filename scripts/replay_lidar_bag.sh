#!/usr/bin/env bash
set -euo pipefail

if [ "$#" -ne 1 ]; then
  echo "Usage: $0 <bag-directory>" >&2
  exit 2
fi

if [ ! -d "$1" ]; then
  echo "Bag directory does not exist: $1" >&2
  exit 2
fi

exec ros2 bag play "$1" --clock
