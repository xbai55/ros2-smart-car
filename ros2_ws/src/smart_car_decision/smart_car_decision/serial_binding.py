"""Read-only USB identity validation. This module never opens a serial port."""
import json
import os
import re
import stat
import subprocess
from pathlib import Path


class BindingError(RuntimeError):
    pass


def validate_profile(profile, *, confirmed=True):
    if profile.get("schema") != 1:
        raise BindingError("unsupported binding schema")
    service_user = profile.get('service_user')
    if service_user is not None and (not isinstance(service_user, str) or
                                    not re.fullmatch(r'[a-z_][a-z0-9_-]{0,31}', service_user)):
        raise BindingError('invalid serial service account')
    roles = profile.get("roles", {})
    if "base" not in roles or set(roles) - {"base", "smoke"}:
        raise BindingError("base required; only verified base/smoke roles supported")
    identities = set()
    for role, spec in roles.items():
        if spec.get("alias") != {"base": "/dev/robot_base", "smoke": "/dev/smoke_sensor"}[role]:
            raise BindingError("legacy or arbitrary serial aliases are forbidden")
        match = spec.get("match", {})
        if not {"ID_VENDOR_ID", "ID_MODEL_ID", "ID_USB_INTERFACE_NUM"} <= match.keys():
            raise BindingError("VID/PID/interface required")
        selectors = set(match) & {"ID_SERIAL_SHORT", "ID_PATH"}
        if len(selectors) != 1 or set(match) - {"ID_VENDOR_ID", "ID_MODEL_ID", "ID_USB_INTERFACE_NUM", *selectors}:
            raise BindingError("one stable serial number OR physical path required")
        for key, value in match.items():
            if not isinstance(value, str) or not re.fullmatch(r"[A-Za-z0-9_.:+/-]+", value):
                raise BindingError("unsafe/empty udev selector")
        for key in ("ID_VENDOR_ID", "ID_MODEL_ID"):
            if not re.fullmatch(r"[0-9a-f]{4}", match[key]):
                raise BindingError("invalid VID/PID")
        identity = tuple(sorted(match.items()))
        if identity in identities:
            raise BindingError("two roles claim the same physical identity")
        identities.add(identity)
        if confirmed and (spec.get("confirmed") is not True or not spec.get("evidence")):
            raise BindingError(f"{role}: physical role is not confirmed")
    return roles


def load_profile(path="/etc/insightrover/serial-binding.json"):
    profile = json.loads(Path(path).read_text(encoding="utf-8"))
    validate_profile(profile)
    return profile


def collect_devices():
    devices = []
    for p in sorted(Path("/sys/class/tty").glob("ttyUSB*")):
        q = subprocess.run(["udevadm", "info", "--query=property", "--name", "/dev/" + p.name],
                           check=True, capture_output=True, text=True, timeout=5)
        props = dict(line.split("=", 1) for line in q.stdout.splitlines() if "=" in line)
        devices.append({"device": "/dev/" + p.name, "properties": props})
    return devices


def select_device(profile, devices, role="base"):
    spec = validate_profile(profile)[role]
    matches = [d for d in devices if all(d["properties"].get(k) == v for k, v in spec["match"].items())]
    if len(matches) != 1:
        raise BindingError(f"{role}: expected one identity match, found {len(matches)}")
    for other, other_spec in profile['roles'].items():
        if other != role and all(matches[0]['properties'].get(k) == v for k, v in other_spec['match'].items()):
            raise BindingError(f"{role} and {other} match the same connected device")
    return matches[0]["device"]


def holders(device):
    """Unreadable process tables cannot be treated as an ownership clearance."""
    result, inaccessible = [], []
    target = os.stat(device).st_rdev
    for proc in Path("/proc").iterdir():
        if not proc.name.isdigit() or int(proc.name) == os.getpid():
            continue
        try:
            for fd in (proc / "fd").iterdir():
                try:
                    info = fd.stat()
                    if stat.S_ISCHR(info.st_mode) and info.st_rdev == target:
                        result.append({"pid": int(proc.name), "fd": fd.name})
                except FileNotFoundError:
                    pass
        except FileNotFoundError:
            pass
        except PermissionError:
            inaccessible.append(int(proc.name))
    if inaccessible:
        # Normal service users cannot inspect root-owned /proc fds. An existing
        # passwordless sudo grant may run fuser read-only; NEVER use its -k flag.
        q = subprocess.run(["sudo", "-n", "/usr/bin/fuser", device],
                           capture_output=True, text=True, timeout=5)
        if q.returncode not in (0, 1) or (q.returncode == 1 and q.stderr.strip()):
            raise BindingError("cannot verify ownership with privileged read-only fuser")
        try:
            pids = [int(p) for p in q.stdout.split()]
        except ValueError as exc:
            raise BindingError("invalid ownership audit output") from exc
        if q.returncode == 0 and not pids:
            raise BindingError("ownership audit reported use without process identities")
        result = [{"pid": pid, "fd": "privileged-fuser"} for pid in pids if pid != os.getpid()]
    return result


def preflight(profile, *, devices=None, check_holders=holders):
    device = select_device(profile, collect_devices() if devices is None else devices)
    alias = profile["roles"]["base"]["alias"]
    if not Path(alias).exists() or Path(alias).resolve() != Path(device).resolve():
        raise BindingError("robot_base alias missing or points to a different device")
    if not stat.S_ISCHR(os.stat(alias).st_mode):
        raise BindingError("base must be a character device")
    occupied = check_holders(device)
    if occupied:
        raise BindingError(f"base is occupied: {occupied}")
    return device


def render_rules(profile):
    roles = validate_profile(profile)
    lines = ['# Generated from confirmed physical roles; moving a USB plug requires revalidation.',
             'ACTION!="add|change", GOTO="insightrover_serial_end"',
             'SUBSYSTEM!="tty", GOTO="insightrover_serial_end"']
    for spec in roles.values():
        terms = [f'ENV{{{k}}}=="{v}"' for k, v in sorted(spec["match"].items())]
        access = [f'OWNER="{profile["service_user"]}"', 'MODE="0600"'] if profile.get('service_user') else ['GROUP="dialout"', 'MODE="0660"']
        lines.append(', '.join(terms + access + [
                                       f'SYMLINK+="{Path(spec["alias"]).name}"']))
    return '\n'.join(lines + ['LABEL="insightrover_serial_end"', ''])


def remove_legacy_alias(text):
    """Remove only active rules claiming myserial; preserve all other rules."""
    kept = []
    for line in text.splitlines(keepends=True):
        if not line.lstrip().startswith("#") and re.search(r'SYMLINK\s*[:+]?=\s*"[^"\n]*\bmyserial\b', line):
            # Do not silently remove a mixed-purpose rule; require manual splitting.
            aliases = re.findall(r'SYMLINK\s*[:+]?=\s*"([^"]+)"', line)
            if aliases != ["myserial"]:
                raise BindingError("mixed legacy rule requires explicit review")
            continue
        kept.append(line)
    return ''.join(kept)
