"""Build a reviewable vehicle bundle; optionally upload/build in a new directory.

Never stops, starts, or replaces an existing vehicle process. SSH prompts stay local.
"""
import argparse
import hashlib
from io import BytesIO
import json
from pathlib import Path
import shlex
import subprocess
import sys
import tarfile
from datetime import datetime
from uuid import uuid4


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--upload', action='store_true')
    parser.add_argument('--check', action='store_true', help='check the local launcher without connecting to the car')
    args = parser.parse_args()
    repo = Path(__file__).resolve().parents[1]
    workspace = repo.parent
    out = repo / 'output/safety-patrol-20261017'
    out.mkdir(parents=True, exist_ok=True)
    package = repo / 'ros2_ws/src/smart_car_decision'
    release_id = datetime.now().strftime('%Y%m%d-%H%M%S') + '-' + uuid4().hex[:8]
    archive_path = out / f'vehicle-inspection-release-{release_id}.tar.gz'
    hashes = {}
    with tarfile.open(archive_path, 'w:gz') as archive:
        for path in sorted(package.rglob('*')):
            if not path.is_file() or '__pycache__' in path.parts or path.suffix == '.pyc':
                continue
            relative = path.relative_to(repo).as_posix()
            content = path.read_bytes()
            hashes[relative] = hashlib.sha256(content).hexdigest()
            entry = tarfile.TarInfo(relative)
            entry.size = len(content)
            entry.mode = 0o644
            archive.addfile(entry, BytesIO(content))
        data = json.dumps(hashes, indent=2).encode()
        entry = tarfile.TarInfo('source-sha256.json')
        entry.size = len(data)
        archive.addfile(entry, BytesIO(data))
    manifest = {'archive': str(archive_path), 'sha256': hashlib.sha256(archive_path.read_bytes()).hexdigest(),
                'status': 'local_bundle_only', 'activation': 'not_started', 'files': len(hashes)}
    manifest_path = out / 'deployment.json'
    manifest_path.write_text(json.dumps(manifest, indent=2), encoding='utf-8')
    print('Vehicle bundle prepared:', archive_path, flush=True)
    if not args.upload:
        return
    sys.path.insert(0, str(workspace))
    from startup_config import load_car_ip
    ip = load_car_ip()
    remote_name = 'ros2-smart-car-inspection-' + datetime.now().strftime('%Y%m%d-%H%M%S')
    upload = '/home/jetson/' + remote_name + '.tar.gz'
    remote = '/home/jetson/' + remote_name
    subprocess.run(['scp', str(archive_path), f'jetson@{ip}:{upload}'], check=True)
    commands = f'''set -eu
test ! -e {shlex.quote(remote)}
mkdir -p {shlex.quote(remote)}
echo '{manifest['sha256']}  {upload}' | sha256sum -c -
tar -xzf {shlex.quote(upload)} -C {shlex.quote(remote)}
cd {shlex.quote(remote)}
python3 - <<'PY'
import hashlib,json
from pathlib import Path
for name,expected in json.loads(Path('source-sha256.json').read_text()).items():
    assert hashlib.sha256(Path(name).read_bytes()).hexdigest()==expected,name
print('Source hashes verified')
PY
cat /proc/device-tree/model
cat /etc/nv_tegra_release
free -h
source /opt/ros/humble/setup.bash
cd ros2_ws
colcon build --packages-select smart_car_decision
echo 'Staging build complete. Existing vehicle processes have not been changed.'
'''
    subprocess.run(['ssh', '-t', f'jetson@{ip}', 'bash -lc ' + shlex.quote(commands)], check=True)
    manifest.update(status='uploaded_and_built_not_activated', remote=remote)
    manifest_path.write_text(json.dumps(manifest, indent=2), encoding='utf-8')
    print('Staged at:', remote, flush=True)


if __name__ == '__main__':
    main()
