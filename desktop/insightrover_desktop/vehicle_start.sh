#!/usr/bin/env bash
# Session startup only. Never changes autostart or sends motion commands.
set -eo pipefail
entry=/home/jetson/ros2-smart-car-mapping-settings-20261020/start_test.sh
unit=smart-car-mapping-settings-20261020.service
[[ -f "$entry" ]] || { echo 'CAR_NOT_DEPLOYED'; exit 20; }

# An already running stack, including an active task, must remain untouched.
if systemctl --user is-active --quiet "$unit"; then
    echo 'CAR_ALREADY_RUNNING'; exit 0
fi
for old_unit in smart-car-camera-fix-20261014.service smart-car-mapping-fix-20261013.service smart-car-current-test-20261013.service smart-car-current-test-20261008.service smart-car-test-20261008.service smart-car-restored-20261008.service; do
    systemctl --user stop "$old_unit" 2>/dev/null || true
done
vendor='^python3 /home/jetson/Rosmaster/rosmaster/rosmaster_main.py$'
if pgrep -f "$vendor" >/dev/null; then
    pkill -INT -f "$vendor" || true
    sleep 2
    if pgrep -f "$vendor" >/dev/null; then pkill -TERM -f "$vendor" || true; sleep 1; fi
    if pgrep -f "$vendor" >/dev/null; then echo 'VENDOR_STILL_RUNNING'; exit 21; fi
fi
python3 - <<'PY'
import socket
for port in (8080, 9999):
    with socket.socket() as probe:
        probe.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try: probe.bind(('127.0.0.1', port))
        except OSError: raise SystemExit('CAR_PORT_IN_USE')
PY
if [[ "$(systemctl --user show "$unit" -p LoadState --value)" == loaded ]]; then
    systemctl --user start "$unit"
else
    systemd-run --user --unit="$unit" --property=Restart=on-failure --property=RestartSec=3 \
        --property=KillSignal=SIGINT --property=TimeoutStopSec=30 /bin/bash "$entry"
fi
echo 'CAR_START_REQUESTED'
