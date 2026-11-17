"""Exercise the installed host's normal mapping entry, without any drive commands."""
import asyncio
from datetime import timedelta
import json
import os
from pathlib import Path
import secrets
import socket
import subprocess
import sys
import threading
import time

import httpx

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT/'desktop'), str(ROOT/'backend')]
from insightrover_desktop.config import AppConfig


def main():
    out = ROOT/'output/mapping-fix-20261116'
    out.mkdir(parents=True, exist_ok=True)
    config = AppConfig('C:/Users/xbai55/AppData/Local/InsightRover')
    os.environ.update(config.environment())
    from sqlalchemy import select
    from app.db.session import SessionLocal
    from app.models import User
    from app.core.security import create_access_token
    with SessionLocal() as db:
        user = next(u for u in db.scalars(select(User)).all() if u.active and
                    {'robots.read', 'robots.control', 'maps.read', 'maps.manage'} <= u.permissions)
        token = create_access_token(user.id, config.value['jwt_secret'], expires_delta=timedelta(minutes=5))
    with socket.socket() as listener:
        listener.bind(('127.0.0.1', 0))
        port = listener.getsockname()[1]
    base = f'http://127.0.0.1:{port}'
    control_token = secrets.token_urlsafe(32)
    env = config.environment()
    env['INSIGHTROVER_CONTROL_TOKEN'] = control_token
    exe = 'C:/Users/xbai55/AppData/Local/Programs/InsightRover/InsightRover.exe'
    record = {'motion_commands_sent': False, 'samples': [], 'passed': False, 'websocket_frames': 0}
    done, connected = threading.Event(), threading.Event()
    def monitor():
        async def run():
            from websockets.legacy.client import connect
            try:
                async with connect(base.replace('http:', 'ws:')+'/ws/status',
                                   open_timeout=5, max_size=8*1024*1024) as ws:
                    await ws.send(json.dumps({'type':'authenticate','token':token}))
                    await asyncio.wait_for(ws.recv(), 5)
                    record['websocket_frames'] += 1
                    connected.set()
                    while not done.is_set():
                        try:
                            await asyncio.wait_for(ws.recv(), 1)
                            record['websocket_frames'] += 1
                        except TimeoutError:
                            pass
            except Exception as exc:
                record['websocket_error_type'] = type(exc).__name__
        asyncio.run(run())
    log = (out/'stationary-host.log').open('w', encoding='utf-8')
    process = subprocess.Popen([exe, '--serve', '--port', str(port), '--data-dir', str(config.root)],
                               env=env, stdout=log, stderr=subprocess.STDOUT,
                               creationflags=subprocess.CREATE_NO_WINDOW)
    thread = None
    with httpx.Client(base_url=base, headers={'Authorization':'Bearer '+token}, trust_env=False, timeout=6) as client:
        try:
            deadline = time.monotonic()+30
            while time.monotonic()<deadline:
                if process.poll() is not None:
                    raise RuntimeError('更新后的后台启动失败')
                try:
                    health = client.get('/desktop/health')
                    if health.status_code == 200:
                        record['host_version'] = health.json()['version']
                        break
                except httpx.HTTPError:
                    pass
                time.sleep(.2)
            else:
                raise RuntimeError('后台启动超时')
            initial = client.get('/api/control/status')
            initial.raise_for_status()
            assert initial.json()['mode']=='stop', '验证前必须停车'
            thread = threading.Thread(target=monitor, daemon=True)
            thread.start()
            assert connected.wait(5), '状态推送未连接'
            started = time.monotonic()
            response = client.post('/api/mapping/restart', json={}, timeout=45)
            record['startup_http_status'] = response.status_code
            record['startup_elapsed_sec'] = round(time.monotonic()-started, 3)
            record['startup_response'] = response.json()
            response.raise_for_status()
            session = response.json()['session_id']
            record['session_id'] = session
            print(json.dumps({'mapping_started':session,'startup_sec':record['startup_elapsed_sec']}),flush=True)
            started = time.monotonic()
            while time.monotonic()-started < 60:
                before = time.monotonic()
                response = client.get('/api/control/status')
                response.raise_for_status()
                value = response.json()
                mapping, odom, lease = value.get('mapping',{}), value.get('odom',{}), value.get('control_lease',{})
                row = {'elapsed_sec':round(time.monotonic()-started, 2),'http_sec':round(time.monotonic()-before,3),
                       'mode':value.get('mode'),'mapping_state':mapping.get('state'),'error':mapping.get('error'),
                       'recording':mapping.get('recording',{}).get('state'),
                       'lease_blocked':lease.get('blocked'),'lease_sequence':lease.get('sequence'),
                       'linear_speed_xy':odom.get('linear_speed_xy'),'angular_speed':odom.get('angular_speed')}
                record['samples'].append(row)
                (out/'stationary-progress.json').write_text(json.dumps(record,ensure_ascii=False,indent=2),encoding='utf-8')
                assert value.get('mode')=='mapping', '建图模式提前退出'
                assert mapping.get('session_id')==session, '建图会话已变化'
                assert mapping.get('state')!='error', mapping.get('error')
                assert abs(odom.get('linear_speed_xy',1))<.02, '检测到车辆位移速度，结束验证'
                assert lease.get('blocked') is False, '控制授权中断'
                assert row['recording']=='recording', '完整输入录制中断'
                if mapping.get('state')=='ready' and 'first_map' not in record:
                    grid = client.get('/api/control/map')
                    grid.raise_for_status()
                    g = grid.json()
                    record['first_map'] = {k:g.get(k) for k in ['session_id','revision','info']}
                    record['recording_directory'] = mapping['recording']['directory']
                time.sleep(1)
            assert 'first_map' in record, '没有收到有效首张地图'
            assert record['samples'][-1]['mapping_state']=='ready', '建图未保持就绪'
            assert record['samples'][-1]['lease_sequence']>record['samples'][0]['lease_sequence'], '没有有效续约'
            assert record['websocket_frames']>30, '状态推送未持续响应'
            record['passed'] = True
        except Exception as exc:
            record['error'] = str(exc)[:1800]
        finally:
            try:
                response=client.post('/api/v1/robots/r-001/stop',json={},timeout=20)
                record['stop_status']=response.status_code
                record['stop_result']=response.json()
                time.sleep(1)
                final=client.get('/api/control/status').json()
                record['final_mode']=final.get('mode')
                record['final_mapping']=final.get('mapping')
                record['passed'] = record['passed'] and final.get('mode')=='stop' and record['stop_result'].get('stationary_confirmed') is True
            except Exception as exc:
                record['stop_error_type']=type(exc).__name__
                record['passed']=False
            done.set()
            if thread:
                thread.join(3)
            try:
                client.post('/desktop/quit',headers={'X-InsightRover-Token':control_token})
                process.wait(12)
            except Exception:
                process.terminate()
                process.wait(5)
            log.close()
            (out/'stationary-result.json').write_text(json.dumps(record,ensure_ascii=False,indent=2),encoding='utf-8')
            print(json.dumps({k:v for k,v in record.items() if k not in ['samples','first_map']},ensure_ascii=True),flush=True)
    if not record['passed']:
        raise SystemExit(1)


if __name__=='__main__':
    main()
