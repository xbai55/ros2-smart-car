"""Stage an isolated update and optionally activate it stopped. Never grants a motion lease."""
import argparse
import hashlib
import json
from pathlib import Path
import shlex
import subprocess
import sys

import stage_avoidance_release as remote

ROOT = Path(__file__).resolve().parents[1]


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--host', required=True)
    parser.add_argument('--previous', required=True)
    parser.add_argument('--activate', action='store_true')
    args = parser.parse_args()
    version = '4.0.1'
    subprocess.run([sys.executable, str(ROOT/'scripts/package_vision_source.py')], check=True)
    archive = ROOT/f'releases/v{version}/InsightRover-Vehicle-{version}-source.tar.gz'
    sha = digest(archive)
    target = '/home/jetson/insightrover-v401-agent-'+sha[:12]
    output = ROOT/'output/agent-extension-deployment'
    output.mkdir(parents=True, exist_ok=True)
    fall = ROOT/'ros2_ws/src/smart_car_decision/models/yolo11-fall.pt'
    meta = json.loads((ROOT/'ros2_ws/src/smart_car_decision/config/fall-model.json').read_text(encoding='utf-8'))
    if not fall.is_file():
        subprocess.run([sys.executable, str(ROOT/'scripts/fetch_fall_model.py'), '--output', str(fall)], check=True)
    assert digest(fall) == meta['sha256']
    smoke = ROOT/'../ros2-smart-car/output/safety-patrol-20261017/fire-training-v2/train/weights/best.pt'
    training = json.loads((smoke.parents[2]/'training-manifest.json').read_text(encoding='utf-8'))
    assert digest(smoke) == training['sha256']
    client = remote.connect(args.host)
    try:
        state = json.loads(remote.python(client, f'''
from pathlib import Path
import json,shutil,subprocess
old=Path({args.previous!r}).resolve(); target=Path({target!r})
assert old.is_dir() and old.is_relative_to(Path.home()) and target.parent==Path.home()
assert (old/'start_v4.sh').is_file()
unit=Path.home()/'.config/systemd/user/smart-car-v4.service'
assert str(old) in unit.read_text(), 'Service entry changed; inspect before updating'
assert not subprocess.run(['systemctl','--user','is-active','--quiet','smart-car-v4.service']).returncode==0, 'Existing service is running; refuse to interrupt it'
assert shutil.disk_usage(old).free>{archive.stat().st_size*3+fall.stat().st_size+smoke.stat().st_size+180*1024**2}
assert not target.exists(), 'Staging target exists; inspect instead of overwriting'
target.mkdir();(target/'logs').mkdir()
print(json.dumps({{'target':str(target),'free_bytes':shutil.disk_usage(old).free}}))
'''))
        print(json.dumps(state), flush=True)
        with client.open_sftp() as sftp:
            sftp.put(str(archive), target+'/source.tar.gz')
            sftp.put(str(fall), target+'/yolo11-fall.pt')
            sftp.put(str(smoke), target+'/yolo11-smoke-fire.pt')
        setup = json.loads(remote.python(client, f'''
from pathlib import Path
import hashlib,json,tarfile,yaml,shutil
root=Path({target!r});old=Path({args.previous!r})
assert hashlib.sha256((root/'source.tar.gz').read_bytes()).hexdigest()=={sha!r}
with tarfile.open(root/'source.tar.gz') as package:
 for member in package.getmembers():
  assert (member.isfile() or member.isdir()) and not Path(member.name).is_absolute()
  assert (root/member.name).resolve().is_relative_to(root)
 package.extractall(root)
manifest=json.loads((root/'source-sha256.json').read_text())
for name,expected in manifest.items(): assert hashlib.sha256((root/name).read_bytes()).hexdigest()==expected,name
for filename,expected in {{'yolo11-fall.pt':{meta['sha256']!r},'yolo11-smoke-fire.pt':{training['sha256']!r}}}.items():
 assert hashlib.sha256((root/filename).read_bytes()).hexdigest()==expected
config=root/'ros2_ws/src/smart_car_decision/config/decision.yaml'
new=yaml.safe_load(config.read_text());previous=yaml.safe_load((old/'ros2_ws/src/smart_car_decision/config/decision.yaml').read_text())
for name,node in previous.items():
 if isinstance(node,dict) and isinstance(node.get('ros__parameters'),dict):
  new.setdefault(name,{{}}).setdefault('ros__parameters',{{}}).update(node['ros__parameters'])
new['mode_manager']['ros__parameters']['initial_mode']='stop'
new['web_app_node']['ros__parameters']['static_dir']=str(root/'web-console/dist')
config.write_text(yaml.safe_dump(new,allow_unicode=True,sort_keys=False))
entry=(old/'start_v4.sh').read_text()
(root/'start_v4.sh').write_text(entry.replace(str(old),str(root)))
(root/'start_v4.sh').chmod(0o755)
prefix=[line for line in entry.splitlines() if line.startswith(('source ','export '))]
unit=Path.home()/'.config/systemd/user/smart-car-v4.service'
(root/'previous.service').write_bytes(unit.read_bytes())
print(json.dumps({{'prefix':prefix,'source_files':len(manifest)}}))
'''))
        command = '\n'.join(['set -eo pipefail', 'unset AMENT_PREFIX_PATH COLCON_PREFIX_PATH CMAKE_PREFIX_PATH PYTHONPATH',
                              *setup['prefix'], 'cd '+shlex.quote(target+'/ros2_ws'),
                              'colcon build --symlink-install --packages-select smart_car_decision --event-handlers console_direct+ > '+shlex.quote(target+'/logs/build.log')+' 2>&1'])
        build = remote.run(client, 'bash --noprofile --norc -c '+shlex.quote(command), timeout=240)
        (output/'build.log').write_text(build, encoding='utf-8')
        print('Isolated ROS build completed.', flush=True)
        if args.activate:
            result = remote.python(client, f'''
from pathlib import Path
import json,subprocess,os,time
root=Path({target!r});old=Path({args.previous!r})
# Explicit session update only; do not change autostart or grant a control lease.
vendor='^python3 /home/jetson/Rosmaster/rosmaster/rosmaster_main[.]py$'
if subprocess.run(['pgrep','-f',vendor],capture_output=True).returncode==0:
 subprocess.run(['pkill','-INT','-f',vendor],check=False);time.sleep(2)
 if subprocess.run(['pgrep','-f',vendor],capture_output=True).returncode==0:
  subprocess.run(['pkill','-TERM','-f',vendor],check=False);time.sleep(1)
assert subprocess.run(['pgrep','-f',vendor],capture_output=True).returncode!=0, 'Vendor still running'
assert not subprocess.run(['pgrep','-f','/(web_app_node|decision_controller)( |$)'],capture_output=True,text=True).stdout.strip(),'Another control stack is active'
state=Path.home()/'.ros/insightrover';state.mkdir(parents=True,exist_ok=True)
path=state/'safety-vision.json'
config=json.loads(path.read_text()) if path.is_file() else {{'enabled':True,'rate_hz':5,'confirm_sec':2,'clear_sec':10,'models':[],'corridors':[]}}
if path.exists(): (root/'previous-safety-vision.json').write_bytes(path.read_bytes())
models=config.setdefault('models',[])
for ident,filename,category,mapping,confidence,sha in [
 ('fall-yolo11','yolo11-fall.pt','fallen_person',{{'fallen':'fallen_person'}},.25,{meta['sha256']!r}),
 ('smoke-fire-yolo11','yolo11-smoke-fire.pt','smoke_fire',{{'smoke':'smoke_fire','fire':'smoke_fire'}},.5,{training['sha256']!r})]:
 if not any(category in s.get('class_map',{{}}).values() for s in models):
  models.append({{'id':ident,'path':str(root/filename),'class_map':mapping,'confidence':confidence,'sha256':sha,'validation':'not_evaluated'}})
assert len(models)<=2
config['enabled']=True
temp=path.with_suffix('.tmp');temp.write_text(json.dumps(config));os.replace(temp,path)
unit=Path.home()/'.config/systemd/user/smart-car-v4.service'
unit.write_text((root/'previous.service').read_text().replace(str(old),str(root)))
subprocess.run(['systemctl','--user','daemon-reload'],check=True)
subprocess.run(['systemctl','--user','start','smart-car-v4.service'],check=True)
print(json.dumps({{'target':str(root),'built':True,'activated':True,'model_hashes':[{meta['sha256']!r},{training['sha256']!r}],'motion_requested':False}}))
''', timeout=45)
            state.update(json.loads(result))
        else:
            state.update(built=True, activated=False)
        (output/'deployment.json').write_text(json.dumps(state, indent=2), encoding='utf-8')
        print(json.dumps(state), flush=True)
    finally:
        client.close()


if __name__ == '__main__':
    main()
