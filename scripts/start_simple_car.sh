#!/usr/bin/env bash
# Executed over SSH by startup_car.py; no upload or separate installation needed.
set -eo pipefail

entry=/home/jetson/ros2-smart-car-mapping-settings-20261020/start_test.sh
unit=smart-car-mapping-settings-20261020.service
[[ -f "$entry" ]] || { echo "Missing deployed car entry: $entry" >&2; exit 1; }

if systemctl --user is-active --quiet "$unit"; then
    echo 'The current car service is already running.'
    exit 0
fi

for old_unit in smart-car-camera-fix-20261014.service smart-car-mapping-fix-20261013.service smart-car-current-test-20261013.service smart-car-current-test-20261008.service smart-car-test-20261008.service smart-car-restored-20261008.service; do
    systemctl --user stop "$old_unit" 2>/dev/null || true
done

vendor='^python3 /home/jetson/Rosmaster/rosmaster/rosmaster_main.py$'
if pgrep -f "$vendor" >/dev/null; then
    pkill -INT -f "$vendor" || true
    sleep 2
    if pgrep -f "$vendor" >/dev/null; then
        pkill -TERM -f "$vendor" || true
        sleep 1
    fi
    if pgrep -f "$vendor" >/dev/null; then
        echo 'Vendor program did not exit; car startup cancelled.' >&2
        exit 1
    fi
fi

# Refuse a second controller if an unmanaged car stack is already listening.
python3 - <<'PY'
import socket
for port in (8080, 9999):
    with socket.socket() as probe:
        probe.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            probe.bind(('127.0.0.1', port))
        except OSError:
            raise SystemExit(f'Port {port} is in use. Stop the existing car program first.')
PY

echo 'Starting the current car program. Keep this window open; press Ctrl+C to stop.'
exec /bin/bash "$entry"
