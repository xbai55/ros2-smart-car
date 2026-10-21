"""Installed-app acceptance in isolated data directories, against a fake car only."""
import hashlib,json,os,socket,subprocess,sys,time
from pathlib import Path

import httpx

ROOT=Path(__file__).resolve().parents[2]
OUT=ROOT/'output/windows-app-20261020'
sys.path.insert(0,str(ROOT/'desktop'))
from insightrover_desktop.config import AppConfig


def port():
    with socket.socket() as s:s.bind(('127.0.0.1',0));return s.getsockname()[1]


def wait(url,process):
    with httpx.Client(trust_env=False,timeout=.8) as client:
        for _ in range(100):
            if process.poll() is not None:raise RuntimeError('Test server exited')
            try:
                if client.get(url).status_code==200:return
            except httpx.HTTPError:pass
            time.sleep(.15)
    raise RuntimeError('Test readiness timeout '+url)


def run(exe,installer=None):
    root=OUT/('acceptance-'+str(time.time_ns()));root.mkdir(parents=True)
    data=root/'用户数据';config=AppConfig(data)
    fake_port,server_port=port(),port();config.set_address('127.0.0.1',fake_port)
    password='acceptance-test-only'
    subprocess.run([sys.executable,str(ROOT/'desktop/desktop_entry.py'),'--initialize-stdin','--data-dir',str(data)],
                   input=json.dumps({'username':'acceptadmin','password':password}),text=True,check=True)
    secret=config.value['jwt_secret']
    # A map's actual bytes are separate from its database record.
    storage=data/'storage/maps/upgrade-fixture';storage.mkdir(parents=True)
    map_file=storage/'map.pgm';map_file.write_bytes(b'P5\n2 2\n255\n\x00\xfe\xcd\x00')
    expected_hash=hashlib.sha256(map_file.read_bytes()).hexdigest()
    environment=os.environ.copy()
    environment.pop('PYTHONHOME',None);environment.pop('PYTHONPATH',None)
    environment.pop('TCL_LIBRARY',None);environment.pop('TK_LIBRARY',None)
    environment['PATH']=os.environ['SystemRoot']+'\\System32;'+os.environ['SystemRoot']
    environment['INSIGHTROVER_CONTROL_TOKEN']='isolated-test-control'
    flags=subprocess.CREATE_NO_WINDOW if os.name=='nt' else 0
    fake_log=(root/'fake-car.log').open('wb')
    fake=subprocess.Popen([sys.executable,str(ROOT/'desktop/tests/fake_car.py'),str(fake_port)],stdout=fake_log,stderr=fake_log,creationflags=flags)
    wait(f'http://127.0.0.1:{fake_port}/api/status',fake)
    result={'clean_path':environment['PATH'],'gui':False,'rounds':[]}
    try:
        # Verify Tcl/Tk is bundled, without opening a visible test window.
        gui=subprocess.run([str(exe),'--check-gui','--data-dir',str(data)],env=environment,timeout=15,creationflags=flags)
        assert gui.returncode==0 and json.loads((data/'gui-check.json').read_text())['tk']
        result['gui']=True
        vehicle=subprocess.run([str(exe),'--check-vehicle','--data-dir',str(data)],env=environment,timeout=15,creationflags=flags)
        assert vehicle.returncode==0 and json.loads((data/'vehicle-check.json').read_text())['wifi_worker']
        result['ssh_and_wifi_bundled']=True
        map_id=None
        for round_number in (1,2):
            if round_number==2:
                (data/'data-version.txt').write_text('0.2.0')
                if installer:
                    subprocess.run([str(installer),'/VERYSILENT','/SUPPRESSMSGBOXES','/NORESTART','/NOICONS',
                                    '/DIR='+str(exe.parent),'/LOG='+str(root/'upgrade.log')],check=True,timeout=60)
            backend_log=(root/f'backend-{round_number}.log').open('wb')
            process=subprocess.Popen([str(exe),'--serve','--port',str(server_port),'--data-dir',str(data)],
                                     env=environment,stdout=backend_log,stderr=backend_log,creationflags=flags)
            base=f'http://127.0.0.1:{server_port}'
            try:
                wait(base+'/desktop/health',process)
                with httpx.Client(base_url=base,trust_env=False,timeout=10) as client:
                    assert client.get('/').status_code==200
                    login=client.post('/api/v1/auth/login',json={'username':'acceptadmin','password':password});assert login.status_code==200,login.text
                    assert login.json()['user']['role']['name']=='admin'
                    headers={'Authorization':'Bearer '+login.json()['access_token']}
                    assert client.post('/api/v1/auth/login',json={'username':'admin','password':'admin123'}).status_code==401
                    assert client.get('/api/status').json()['mode']=='stop'
                    assert client.get('/api/video?frame=true').content==b'fake-frame'
                    assert b'fixture' in client.get('/video_feed').content
                    assert client.post('/api/mapping/settings',json={'max_laser_range':.5}).json()['settings']['max_laser_range']==.5
                    if round_number==1:
                        response=client.post('/api/v1/maps',json={'name':'升级保留验证','width':2,'height':2,'image_key':'maps/upgrade-fixture/map.pgm'},headers=headers)
                        assert response.status_code==201,response.text
                        map_id=response.json()['id']
                    assert client.get('/api/v1/maps/'+map_id,headers=headers).json()['name']=='升级保留验证'
                    assert client.get('/api/v1/media/object/maps/upgrade-fixture/map.pgm',headers=headers).content==map_file.read_bytes()
                    from websockets.sync.client import connect
                    with connect(base.replace('http:','ws:')+'/ws/status',proxy=None,open_timeout=5) as ws:
                        assert json.loads(ws.recv(timeout=5))['mode']=='stop'
                    assert client.post('/desktop/quit').status_code==403
                    client.post('/desktop/quit',headers={'X-InsightRover-Token':'isolated-test-control'})
                process.wait(timeout=15)
                result['rounds'].append({'round':round_number,'login':True,'http_proxy':True,'video':True,'websocket':True,'map_retained':True,'exit_code':process.returncode})
            finally:
                if process.poll() is None:process.terminate();process.wait(timeout=5)
                backend_log.close()
            assert hashlib.sha256(map_file.read_bytes()).hexdigest()==expected_hash
            assert AppConfig(data).value['jwt_secret']==secret
            assert AppConfig(data).value['ip']=='127.0.0.1'
        assert list((data/'backups').glob('*/smart_patrol.db'))
        result['upgrade_backup']=True;result['data_dir']=str(data);result['map_sha256']=expected_hash
        (OUT/'acceptance-result.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
        print(json.dumps(result,ensure_ascii=False,indent=2))
    finally:
        fake.terminate();fake.wait(timeout=5);fake_log.close()


if __name__=='__main__':run(Path(sys.argv[1]).resolve(),Path(sys.argv[2]).resolve() if len(sys.argv)>2 else None)
