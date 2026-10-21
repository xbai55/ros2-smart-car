"""Prepare a local review bundle only; never connects to or restarts the vehicle."""
import hashlib
import json
import tarfile
from pathlib import Path
from io import BytesIO


def main():
    root=Path(__file__).resolve().parents[1]
    output=root/'output/mapping-settings-20261020'
    output.mkdir(parents=True,exist_ok=True)
    package=root/'ros2_ws/src/smart_car_decision'
    paths=[p for folder in [package,root/'web-console/dist'] for p in folder.rglob('*')
           if p.is_file() and '__pycache__' not in p.parts and p.suffix!='.pyc']
    paths += [root/'scripts/inspect_mapping_log.py',root/'docs/mapping-settings-and-recordings.md']
    if not (root/'web-console/dist/index.html').exists():
        raise SystemExit('Build the web console first')
    hashes={p.relative_to(root).as_posix():hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(paths)}
    archive=output/'mapping-settings-release.tar.gz'
    with tarfile.open(archive,'w:gz') as tar:
        for path in sorted(paths):
            tar.add(path,arcname=path.relative_to(root).as_posix(),recursive=False)
        content=json.dumps(hashes,ensure_ascii=False,indent=2).encode()
        info=tarfile.TarInfo('source-sha256.json');info.size=len(content)
        tar.addfile(info,BytesIO(content))
    manifest={'state':'local_verified_not_deployed','archive':str(archive),
              'sha256':hashlib.sha256(archive.read_bytes()).hexdigest(),'files':len(paths),
              'defaults':{'turn_speed':.15,'max_laser_range':3.},'vehicle_restarted':False}
    (output/'release.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(manifest,ensure_ascii=False,indent=2))


if __name__=='__main__':main()
