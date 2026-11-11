#!/usr/bin/env bash
# Session startup only. Never changes autostart or sends motion commands.
set -eo pipefail
unit=smart-car-v4.service
[[ "$(systemctl --user show "$unit" -p LoadState --value)" == loaded ]] || {
    echo 'CAR_NOT_DEPLOYED'; exit 20;
}

# An already running stack, including an active task, must remain untouched.
if systemctl --user is-active --quiet "$unit"; then
    echo 'CAR_ALREADY_RUNNING'; exit 0
fi
# Refuse to replace a different InsightRover control stack.
if pgrep -f '(/web_app_node|/decision_controller)( |$)' >/dev/null; then
    echo 'CAR_OTHER_STACK_RUNNING'; exit 22
fi

# Stop only the known vendor controller before starting this session.
vendor='^python3 /home/jetson/Rosmaster/rosmaster/rosmaster_main[.]py$'
if pgrep -f "$vendor" >/dev/null; then
    pkill -INT -f "$vendor" || true
    sleep 2
    if pgrep -f "$vendor" >/dev/null; then
        pkill -TERM -f "$vendor" || true
        sleep 1
    fi
    if pgrep -f "$vendor" >/dev/null; then
        echo 'VENDOR_STILL_RUNNING'; exit 21
    fi
fi
python3 - <<'PY'
import socket
for port in (8080, 9999):
    with socket.socket() as probe:
        probe.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try: probe.bind(('127.0.0.1', port))
        except OSError: raise SystemExit('CAR_PORT_IN_USE')
PY
systemctl --user start "$unit"
echo 'CAR_START_REQUESTED'
