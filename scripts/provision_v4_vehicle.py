"""Prepare persistent vision and an authenticated, stopped v4 service.

Does not start or enable the service. Uses the existing pinned SSH connection.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import secrets
import shlex
import sys
import time

import stage_avoidance_release as remote

ROOT = Path(__file__).resolve().parents[1]


def digest(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", required=True)
    args = parser.parse_args()
    output = ROOT / "output/v4-vehicle-preflight"
    stage = json.loads((output / "staged-v4.json").read_text())
    assert stage["built"] is True and stage["started"] is False
    target = stage["target"]
    models = ROOT / "output/vision-search-20261028"
    files = {name: models / name for name in ("yoloe-11s-seg.pt", "mobileclip_blt.ts")}
    hashes = {name: digest(path) for name, path in files.items()}
    client = remote.connect(args.host)
    try:
        layout = json.loads(remote.python(client, f'''
from pathlib import Path
import json,shutil,subprocess
root=Path({target!r}); assert root.is_dir()
assert not subprocess.run(["pgrep","-f","/(web_app_node|decision_controller)( |$)"],capture_output=True,text=True).stdout.strip()
vision=Path.home()/".local/share/insightrover/vision-v4"
vision.mkdir(parents=True,exist_ok=True)
for name in ("models","packages","settings"): (vision/name).mkdir(exist_ok=True)
required={sum(p.stat().st_size for p in files.values())}
existing=sum(p.stat().st_size for p in (vision/"models").glob("*.pt"))+sum(p.stat().st_size for p in (vision/"models").glob("*.ts"))
assert shutil.disk_usage(vision).free>max(0,required-existing)+256*1024**2,"Insufficient persistent storage"
print(json.dumps({{"vision":str(vision)}}))
'''))
        vision = layout["vision"]
        with client.open_sftp() as sftp:
            for name, path in files.items():
                destination = vision + "/models/" + name
                matches = remote.python(client,
                    "from pathlib import Path\nimport hashlib\np=Path(" + repr(destination) +
                    ")\nprint(p.is_file() and hashlib.sha256(p.read_bytes()).hexdigest()==" + repr(hashes[name]) + ")").strip() == "True"
                if not matches:
                    print("Uploading persistent model: " + name, flush=True)
                    started = time.monotonic()
                    sftp.put(str(path), destination + ".partial")
                    remote.python(client, f'''
from pathlib import Path
import hashlib,os
p=Path({destination + ".partial"!r})
assert hashlib.sha256(p.read_bytes()).hexdigest()=={hashes[name]!r}
os.replace(p,{destination!r})
''')
                    print(json.dumps({"model": name, "verified": True, "seconds": round(time.monotonic()-started, 1)}), flush=True)
        existing_path = output / "provisioned-v4.json"
        existing = json.loads(existing_path.read_text()) if existing_path.exists() else {}
        if existing.get("vision") == vision and existing.get("clip_commit"):
            commit = existing["clip_commit"]
            remote.python(client, f'''
import sys,importlib.metadata as m
sys.path.insert(0,{vision + "/packages"!r})
for name,version in {{"ultralytics":"8.4.0","ftfy":"6.3.1","regex":"2024.11.6","clip":"1.0"}}.items():
 assert m.version(name)==version,name
import clip,ftfy,regex
print("Verified existing persistent dependencies")
''')
            print("Reusing verified persistent vision dependencies.", flush=True)
        else:
            print("Installing isolated vision dependencies; system packages remain unchanged.", flush=True)
            commit = remote.run(client, "git ls-remote https://github.com/ultralytics/CLIP.git HEAD", timeout=35).split()[0]
            assert len(commit) == 40 and all(c in "0123456789abcdef" for c in commit)
            package = shlex.quote(vision + "/packages")
            command = (
                "PIP_NO_CACHE_DIR=1 python3 -m pip install --no-deps --target " + package +
                " ultralytics==8.4.0 ftfy==6.3.1 regex==2024.11.6 " +
                shlex.quote("git+https://github.com/ultralytics/CLIP.git@" + commit)
            )
            install = remote.run(client, command, timeout=240)
            (output / "vision-dependencies.log").write_text(install, encoding="utf-8")
        profile = hashlib.sha256(os.path.normcase(str(output.resolve())).encode()).hexdigest()
        sys.path.insert(0, str(ROOT / "backend"))
        from app.services.windows_credentials import read_credentials, write_credentials
        credentials = read_credentials(profile)
        token = credentials.get("robot_token") or secrets.token_urlsafe(48)
        credentials["robot_token"] = token
        write_credentials(profile, credentials)
        # Only a dedicated commissioning profile is touched. Never print token bytes.
        with client.open_sftp() as sftp:
            private = "/home/jetson/.config/insightrover"
            try:
                sftp.mkdir(private, mode=0o700)
            except OSError:
                pass
            sftp.chmod(private, 0o700)
            path = private + "/v4-service.env"
            with sftp.open(path, "w") as handle:
                sftp.chmod(path, 0o600)
                handle.write(("ROBOT_SERVICE_TOKEN=" + token + "\n").encode())
        prepared = json.loads(remote.python(client, f'''
from pathlib import Path
import json,shutil,subprocess
root=Path({target!r}); vision=Path({vision!r})
config=Path.home()/".ros/insightrover/vision.json"
previous=json.loads(config.read_text()) if config.exists() else {{}}
backup=root/"previous-state/vision-before-persistent.json"
if config.exists() and not backup.exists(): shutil.copy2(config,backup)
previous["model_path"]=str(vision/"models/yoloe-11s-seg.pt")
config.write_text(json.dumps(previous,indent=2))
setups=list(dict.fromkeys({stage["setups"]!r}))
lines=["#!/usr/bin/env bash","set -eo pipefail",
       "if pgrep -f '^python3 /home/jetson/Rosmaster/rosmaster/rosmaster_main.py$' >/dev/null; then",
       "  echo CAR_VENDOR_CONTROLLER_ACTIVE; exit 21","fi",
       "unset AMENT_PREFIX_PATH COLCON_PREFIX_PATH CMAKE_PREFIX_PATH PYTHONPATH",
       *setups,"source "+str(root/"ros2_ws/install/local_setup.bash"),
       "export ROS_DOMAIN_ID=77","export PYTHONUNBUFFERED=1",
       'export VEHICLE_DIAGNOSTICS_DIR="$'+'{{VEHICLE_DIAGNOSTICS_DIR:-$HOME/.local/share/insightrover/diagnostics}}"',
       "export YOLO_AUTOINSTALL=false","export YOLO_OFFLINE=true",
       "export YOLO_CONFIG_DIR="+str(vision/"settings"),
       'export PYTHONPATH='+str(vision/"packages")+':$'+'{{PYTHONPATH:-}}',
       "cd "+str(root/"ros2_ws"),
       "exec ros2 launch smart_car_decision bringup_all.launch.py start_yolo_camera:=false"]
entry=root/"start_v4.sh";entry.write_text("\\n".join(lines)+"\\n");entry.chmod(0o755)
unit=Path.home()/".config/systemd/user/smart-car-v4.service"
unit.parent.mkdir(parents=True,exist_ok=True)
content="\\n".join(["[Unit]","Description=InsightRover v4 authenticated safe-start",
 "[Service]","Type=simple","EnvironmentFile="+str(Path.home()/".config/insightrover/v4-service.env"),
 "ExecStart=/bin/bash "+str(entry),"KillSignal=SIGINT","TimeoutStopSec=30",
 "Restart=on-failure","RestartSec=3","[Install]","WantedBy=default.target",""])
if unit.exists() and unit.read_text()!=content:
 shutil.copy2(unit,root/"previous-state/smart-car-v4.service")
unit.write_text(content)
subprocess.run(["systemctl","--user","daemon-reload"],check=True)
print(json.dumps({{"unit":unit.name,"entry":str(entry),"vision":str(vision),
 "enabled":False,"started":False,"clip_commit":{commit!r},"model_hashes":{hashes!r}}}))
'''))
        prepared.update(host=args.host, credential_profile=profile)
        (output / "provisioned-v4.json").write_text(json.dumps(prepared, indent=2), encoding="utf-8")
        print(json.dumps(prepared), flush=True)
    finally:
        client.close()


if __name__ == "__main__":
    main()
