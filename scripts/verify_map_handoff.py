"""Stationary installed-app acceptance: fresh SLAM -> auto pose -> preview only."""
from datetime import timedelta
import json
import math
import os
from pathlib import Path
import secrets
import socket
import subprocess
import sys
import time
from uuid import uuid4
import httpx

ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT/'desktop'),str(ROOT/'backend')]
from insightrover_desktop.config import AppConfig


def main():
    out=ROOT/'output/map-handoff-20261116';out.mkdir(parents=True,exist_ok=True)
    config=AppConfig('C:/Users/xbai55/AppData/Local/InsightRover')
    os.environ.update(config.environment())
    from sqlalchemy import select
    from app.db.session import SessionLocal
    from app.models import User
    from app.core.security import create_access_token
    with SessionLocal() as db:
        user=next(u for u in db.scalars(select(User)).all() if u.active and
                  {'robots.read','robots.control','maps.read','maps.manage'}<=u.permissions)
        token=create_access_token(user.id,config.value['jwt_secret'],expires_delta=timedelta(minutes=5))
    with socket.socket() as sock:
        sock.bind(('127.0.0.1',0));port=sock.getsockname()[1]
    env=config.environment();control=secrets.token_urlsafe(32);env['INSIGHTROVER_CONTROL_TOKEN']=control
    log=(out/'stationary-host.log').open('w',encoding='utf-8')
    process=subprocess.Popen(['C:/Users/xbai55/AppData/Local/Programs/InsightRover/InsightRover.exe',
                              '--serve','--port',str(port),'--data-dir',str(config.root)],
                             env=env,stdout=log,stderr=subprocess.STDOUT,creationflags=subprocess.CREATE_NO_WINDOW)
    record={'passed':False,'handoff_passed':False,'preview_passed':False,'motion_commands_sent':False,'preparation_samples':[]}
    with httpx.Client(base_url=f'http://127.0.0.1:{port}',headers={'Authorization':'Bearer '+token},
                      trust_env=False,timeout=10) as c:
        def get(path):
            r=c.get(path);r.raise_for_status();return r.json()
        def post(path,payload,timeout=25):
            r=c.post(path,json=payload,timeout=timeout)
            if not r.is_success: raise RuntimeError(f'{path}: {r.status_code} {r.text[:600]}')
            return r.json()
        try:
            deadline=time.monotonic()+30
            while time.monotonic()<deadline:
                if process.poll() is not None: raise RuntimeError('应用后台启动失败')
                try:
                    record['host_version']=get('/desktop/health')['version'];break
                except httpx.HTTPError: time.sleep(.2)
            else: raise RuntimeError('应用后台启动超时')
            assert record['host_version']=='4.0.5'
            deadline=time.monotonic()+20
            while time.monotonic()<deadline:
                s=get('/api/control/status')
                assert s['mode']=='stop'
                if all(s.get(k,{}).get('ok') for k in ['lidar','odom','tf']): break
                time.sleep(.5)
            start=post('/api/mapping/restart',{},45)
            record['mapping_session']=start['session_id']
            deadline=time.monotonic()+30
            while time.monotonic()<deadline:
                s=get('/api/control/status')
                if s['mapping']['state']=='error': raise RuntimeError(s['mapping']['error'])
                if s['mapping']['state']=='ready': break
                time.sleep(.5)
            else: raise RuntimeError('建图未就绪')
            # Allow a few more scans for the stationary map, without driving.
            time.sleep(3)
            p={'request_id':str(uuid4()),'robot_id':'r-001','session_id':start['session_id'],
               'name':'自动定位静态验证 '+time.strftime('%m-%d %H:%M:%S'),'floor':'1F'}
            job=post('/api/v1/maps/slam/finish-for-tasks',p)
            assert post('/api/v1/maps/slam/finish-for-tasks',p)['id']==job['id']
            record['preparation_id']=job['id']
            deadline=time.monotonic()+70
            while time.monotonic()<deadline:
                job=get('/api/v1/maps/slam/preparations/'+job['id'])
                if not record['preparation_samples'] or record['preparation_samples'][-1]['phase']!=job['phase']:
                    record['preparation_samples'].append(job)
                    print(json.dumps(job,ensure_ascii=True),flush=True)
                if job['state'] not in {'pending','running'}: break
                time.sleep(.5)
            assert job['state']=='completed',job['message']
            record['map_id']=job['map_id']
            item=get('/api/v1/maps/'+job['map_id'])
            live=get('/api/control/map')
            assert item['metadata']['digest']==live['asset_digest']
            record['runtime']=get('/api/control/navigation/runtime')
            assert record['runtime']['localized'] is True
            assert get('/api/v1/maps/selection')['map_id']==job['map_id']
            record['handoff_passed']=True
            # Same metadata-derived registration as the task page; no human anchors.
            info=live['info'];w,h,r=info['width'],info['height'],info['resolution'];o=info['origin']
            co,si=math.cos(o['yaw']),math.sin(o['yaw'])
            key=f"map:{w}:{h}:{r:.6f}:{o['x']:.6f}:{o['y']:.6f}:{o['yaw']:.6f}:{live['asset_digest']}"
            drawing={'id':item['id'],'name':item['name'],'kind':'uploaded','width':w,'height':h}
            if item.get('image_key'): drawing['revision']=item['image_key']
            anchors=[{'drawing':{'x':x,'y':y},'world':{'x':o['x']+co*x*r-si*(h-y)*r,
                       'y':o['y']+si*x*r+co*(h-y)*r}} for x,y in [(0,0),(w,0),(0,h),(w,h)]]
            calibrated=post('/api/navigation/calibration',{'anchors':anchors,'map_key':key,'drawing':drawing})
            matrix=calibrated['calibration']['matrix']
            deadline=time.monotonic()+15
            while time.monotonic()<deadline:
                s=get('/api/control/status')
                if s.get('navigation',{}).get('ready'): break
                time.sleep(.5)
            record['navigation']=s.get('navigation')
            pose=s['map_pose']
            # Choose a nearby measured free cell with the unchanged footprint checks.
            sys.path.insert(0,str(ROOT/'ros2_ws/src/smart_car_decision'))
            from smart_car_decision.navigation_config import validate_map_goal
            candidates=[]
            for y in range(h):
                for x in range(w):
                    gx,gy=(x+.5)*r,(y+.5)*r
                    goal={'x':o['x']+co*gx-si*gy,'y':o['y']+si*gx+co*gy,'yaw':pose['yaw']}
                    try: validate_map_goal(goal,live,record['runtime']['robot_radius_m'])
                    except ValueError: continue
                    candidates.append(goal)
            record['safe_goal_count']=len(candidates)
            assert candidates,'当前静态地图没有满足车体安全距离的目标点'
            goal=min(candidates,key=lambda p:math.hypot(p['x']-pose['x'],p['y']-pose['y']))
            record['preview_goal']=goal
            # ComputePath only, never NavigateToPose.
            preview=post('/api/navigation/plan',{'goal':goal,
                         'map_key':key,'calibration_matrix':matrix,'calibration_drawing':drawing})
            record['preview']={'plan_id':preview.get('plan_id'),'points':len(preview.get('path',[]))}
            assert preview.get('plan_id') and preview.get('path')
            record['preview_passed']=True
            record['passed']=True
        except Exception as exc:
            record['error']=str(exc)[:1800]
            try: record['failure_status']=get('/api/control/status')
            except Exception: pass
        finally:
            try:
                record['stop']=post('/api/v1/robots/r-001/stop',{},20)
                record['passed']=record['passed'] and record['stop'].get('stationary_confirmed') is True
            except Exception as exc: record['stop_error']=type(exc).__name__;record['passed']=False
            try:
                c.post('/desktop/quit',headers={'X-InsightRover-Token':control});process.wait(12)
            except Exception: process.terminate();process.wait(5)
            log.close()
            (out/'stationary-result.json').write_text(json.dumps(record,ensure_ascii=False,indent=2),encoding='utf-8')
            print(json.dumps({k:record[k] for k in ['passed','motion_commands_sent','error'] if k in record}),flush=True)
    if not record['passed']: raise SystemExit(1)


if __name__=='__main__':main()
