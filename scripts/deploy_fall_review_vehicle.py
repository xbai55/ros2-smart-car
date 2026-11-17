"""Stage the two vision modules, preserve the current vehicle installation, then activate stopped."""
import argparse
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import shlex
import sys
import urllib.request

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/'backend'))
from app.services.windows_credentials import read_credentials


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--host', required=True)
    parser.add_argument('--activate', action='store_true')
    parser.add_argument('--component', choices=['fall-review', 'mapping-fix', 'map-handoff', 'vehicle-size'], default='fall-review')
    args = parser.parse_args()
    spec = importlib.util.spec_from_file_location('vehicle_connection', ROOT.parent/'output/system-test-20261008/car_deploy.py')
    helper = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(helper)
    helper.HOST = args.host
    out = ROOT/('output/'+args.component+'-20261116')
    out.mkdir(parents=True, exist_ok=True)
    package = ROOT/'ros2_ws/src/smart_car_decision/smart_car_decision'
    names = (['mapping_session.py', 'mapping_recording.py', 'web_api.py', 'web_app_node.py', 'vision_service.py']
             if args.component == 'mapping-fix' else ['safety_events.py', 'safety_vision.py'])
    files = {n: (package/n).read_bytes() for n in names}
    if args.component == 'map-handoff':
        files = {n:(package/n).read_bytes() for n in ['map_handoff.py','web_api.py','web_app_node.py']}
    if args.component == 'vehicle-size':
        files = {n:(package/n).read_bytes() for n in ['vehicle_geometry.py','web_app_node.py','../config/navigation.yaml','../launch/navigation.launch.py']}
    digest = hashlib.sha256(b''.join(files.values())).hexdigest()[:12]
    target = '/home/jetson/insightrover-'+{'mapping-fix':'v404-mapping-fix-','fall-review':'v403-fall-review-','map-handoff':'v405-map-handoff-','vehicle-size':'v406-vehicle-size-'}[args.component]+digest
    def remote(c, code, timeout=45):
        _, o, e = c.exec_command('python3 -c '+shlex.quote(code), timeout=timeout)
        data, error = o.read().decode(), e.read().decode()
        if o.channel.recv_exit_status():
            raise RuntimeError(error[-2000:])
        return data
    c = helper.connect()
    try:
        stage = remote(c, '''from pathlib import Path
import json,re,shutil,subprocess
h=Path('/home/jetson');unit=h/'.config/systemd/user/smart-car-v4.service'
text=unit.read_text();match=re.search(r'^ExecStart=/bin/bash (.+)/start_v4.sh$',text,re.M)
assert match, 'Unknown service entry'
old=Path(match.group(1)).resolve();target=Path('''+repr(target)+''')
assert old.parent==h and target.parent==h and old!=target
assert shutil.disk_usage(h).free>200*1024**2
if target.exists():
 assert not target.is_symlink() and (target/'previous.service').read_text()==text, 'Unrecognized staging directory'
else:
 shutil.copytree(old,target,symlinks=True)
for name in ['build','install','log']:
 p=target/'ros2_ws'/name
 if p.exists():
  assert not p.is_symlink() and p.resolve().is_relative_to(target)
  shutil.rmtree(p)
(target/'start_v4.sh').write_text((old/'start_v4.sh').read_text().replace(str(old),str(target)))
(target/'previous.service').write_text(text)
config=target/'ros2_ws/src/smart_car_decision/config/decision.yaml'
if config.exists(): config.write_text(config.read_text().replace(str(old),str(target)))
print(json.dumps({'previous':str(old),'target':str(target)}))
''')
        state = json.loads(stage)
        print(json.dumps(state), flush=True)
        with c.open_sftp() as sftp:
            for name, data in files.items():
                path = target+'/ros2_ws/src/smart_car_decision/smart_car_decision/'+name
                with sftp.file(path, 'wb') as f:
                    f.write(data)
        checks = {name: hashlib.sha256(data).hexdigest() for name, data in files.items()}
        build = remote(c, '''from pathlib import Path
import hashlib,subprocess,shlex,json
root=Path('''+repr(target)+''');checks='''+repr(checks)+'''
for name,digest in checks.items(): assert hashlib.sha256((root/'ros2_ws/src/smart_car_decision/smart_car_decision'/name).read_bytes()).hexdigest()==digest
entry=(root/'start_v4.sh').read_text()
prefix=[line for line in entry.splitlines() if line.startswith(('source ','export ')) and str(root) not in line]
command=chr(10).join(['set -eo pipefail','unset AMENT_PREFIX_PATH COLCON_PREFIX_PATH CMAKE_PREFIX_PATH PYTHONPATH',*prefix,'cd '+shlex.quote(str(root/'ros2_ws')),'colcon build --symlink-install --packages-select smart_car_decision --event-handlers console_direct+'])
with (root/'logs/fall-review-build.log').open('w') as log:
 result=subprocess.run(['bash','--noprofile','--norc','-c',command],stdout=log,stderr=subprocess.STDOUT)
assert result.returncode==0, 'Build failed; previous service retained'
print(json.dumps({'built':True}))
''', timeout=120)
        state.update(json.loads(build))
        (out/'vehicle-stage.json').write_text(json.dumps(state, indent=2), encoding='utf-8')
        if args.activate:
            data_dir = Path(os.environ['LOCALAPPDATA'])/'InsightRover'
            profile = hashlib.sha256(os.path.normcase(str(data_dir.resolve())).encode()).hexdigest()
            token = read_credentials(profile)['robot_token']
            request = urllib.request.Request('http://'+args.host+':8080/api/status', headers={'X-InsightRover-Service-Token':token})
            with urllib.request.urlopen(request, timeout=5) as response:
                status = json.load(response)
            assert status.get('mode') == 'stop', 'Vehicle must be stopped before activation'
            odom = status.get('odom', {})
            assert odom.get('ok') and odom.get('odom_age_sec', 99)<.5 and odom.get('linear_speed_xy', 1)<.01 and abs(odom.get('angular_speed', 1))<.02
            result = remote(c, '''from pathlib import Path
import json,subprocess,os,time
h=Path('/home/jetson');root=Path('''+repr(target)+''');unit=h/'.config/systemd/user/smart-car-v4.service'
previous=(root/'previous.service').read_text()
assert unit.read_text()==previous, 'Service changed during staging'
config=h/'.ros/insightrover/safety-vision.json';raw=config.read_bytes();value=json.loads(raw)
fall=next(m for m in value['models'] if m.get('id')=='fall-yolo11')
assert fall['class_map']=={'fallen':'fallen_person'}
(root/'previous-safety-vision.json').write_bytes(raw)
footprint=h/'.ros/insightrover/avoidance-footprint.json';body_raw=footprint.read_bytes()
(root/'previous-avoidance-footprint.json').write_bytes(body_raw)
subprocess.run(['systemctl','--user','stop','smart-car-v4.service'],check=True)
try:
 if '''+repr(args.component == 'fall-review')+''': fall['confidence']=.5
 if '''+repr(args.component == 'vehicle-size')+''':
  body=json.loads(body_raw);old_rectangle=body['rectangle']
  assert abs(old_rectangle['front']-.0935)<1e-9 and abs(old_rectangle['rear']-.1565)<1e-9
  body['rectangle']={'front':.0935,'rear':.1565,'half_width':.1}
  body['self_returns']=[p for p in body.get('self_returns',[]) if -.1565<=p[0]<=.0935 and abs(p[1])<=.1]
  body['operator_measurements_m'].update(length=.25,width=.20)
  body['operator_size_20261116']={'length_m':.25,'width_m':.20,'previous_rectangle':old_rectangle,'reason':'operator explicitly confirmed physical dimensions'}
  temporary=footprint.with_suffix('.tmp');temporary.write_text(json.dumps(body));os.replace(temporary,footprint)
 temp=config.with_suffix('.tmp');temp.write_text(json.dumps(value));os.replace(temp,config)
 unit.write_text(previous.replace('''+repr(state['previous'])+''',str(root)))
 subprocess.run(['systemctl','--user','daemon-reload'],check=True)
 subprocess.run(['systemctl','--user','start','smart-car-v4.service'],check=True)
except BaseException:
 footprint.write_bytes(body_raw)
 config.write_bytes(raw);unit.write_text(previous)
 subprocess.run(['systemctl','--user','daemon-reload'],check=True)
 subprocess.run(['systemctl','--user','start','smart-car-v4.service'],check=False)
 raise
print(json.dumps({'activated':True,'confidence':fall['confidence'],'motion_requested':False}))
''')
            state.update(json.loads(result))
        (out/'vehicle-deployment.json').write_text(json.dumps(state, indent=2), encoding='utf-8')
        print(json.dumps(state), flush=True)
    finally:
        c.close()


if __name__ == '__main__':
    main()
