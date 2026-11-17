"""User-authorized short motion probes through the installed host's normal controls."""
from datetime import timedelta
from pathlib import Path
import json
import math
import os
import sys
import threading
import time
import httpx

ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT/'desktop'),str(ROOT/'backend')]


def main():
    from insightrover_desktop.config import AppConfig
    config=AppConfig('C:/Users/xbai55/AppData/Local/InsightRover')
    os.environ.update(config.environment())
    from sqlalchemy import select
    from app.db.session import SessionLocal
    from app.models import User
    from app.core.security import create_access_token
    with SessionLocal() as db:
        user=next(u for u in db.scalars(select(User)).all() if u.active and {'robots.read','robots.control','maps.manage','maps.read'}<=u.permissions)
        token=create_access_token(user.id,config.value['jwt_secret'],expires_delta=timedelta(minutes=3))
    runtime=json.loads((config.root/'runtime.json').read_text())
    headers={'Authorization':'Bearer '+token}
    out=ROOT/'output/guarded-motion-20261116';out.mkdir(parents=True,exist_ok=True)
    record={'trials':[],'safety_settings_changed':False}
    with httpx.Client(base_url=runtime['url'],headers=headers,trust_env=False,timeout=4) as c:
        def get(path):
            r=c.get(path);r.raise_for_status();return r.json()
        def post(path,value):
            r=c.post(path,json=value)
            if not r.is_success: raise RuntimeError(f'{path}: {r.status_code} {r.text[:300]}')
            return r.json()
        def status():
            s=get('/api/control/status')
            return {k:s.get(k) for k in ['mode','emergency_stop','odom','relative_motion','avoidance','motion_settings','speed_scale']}
        def stop(): return post('/api/v1/robots/r-001/stop',{})
        def watchdog():
            try:
                with httpx.Client(base_url=runtime['url'],headers=headers,trust_env=False,timeout=3) as emergency:
                    emergency.post('/api/v1/robots/r-001/stop',json={})
            except Exception: pass
        initial=status();record['initial']=initial
        old_speed=initial['speed_scale'];old_turn=initial['motion_settings']['turn_speed']
        try:
            assert initial['mode'] in ['stop','mapping','manual']
            assert not initial['emergency_stop']
            assert initial['avoidance']['confirmed'] and initial['avoidance']['settings']['enabled']
            assert initial['odom']['ok'] and abs(initial['odom']['linear_speed_xy'])<.01
            # Preserve the map before ending the user's mapping session.
            grid=get('/api/control/map')
            (out/'map-before-probe.json').write_text(json.dumps(grid),encoding='utf-8')
            assert stop().get('stationary_confirmed') is True
            post('/api/speed',{'scale':.15})
            post('/api/mapping/settings',{'turn_speed':.05})
            for command in ['right','turn_l','turn_r']:
                drive=post('/api/mode',{'mode':'manual'})
                before=status();assert before['relative_motion']['ok'] and before['odom']['ok']
                assert before['avoidance']['confirmed'] and before['avoidance']['settings']['enabled']
                row={'command':command,'before':before};record['trials'].append(row)
                timer=threading.Timer(.8,watchdog);timer.daemon=True;timer.start()
                started=time.monotonic()
                try:
                    row['response']=post('/api/command',{'command':command,'drive_id':drive['drive_id'],'drive_seq':1})
                    time.sleep(.15)
                    row['during']=status()
                finally:
                    row['stop']=stop();row['duration_sec']=time.monotonic()-started
                    timer.cancel();timer.join(4)
                time.sleep(.3)
                row['after']=status()
                a,b=before['relative_motion'],row['after']['relative_motion']
                row['distance_m']=math.hypot(b['x']-a['x'],b['y']-a['y'])
                row['yaw_change_deg']=math.degrees(math.atan2(math.sin(b['yaw']-a['yaw']),math.cos(b['yaw']-a['yaw'])))
                print(json.dumps({'command':command,'distance_m':row['distance_m'],'yaw_change_deg':row['yaw_change_deg'],
                                 'avoidance':row.get('during',{}).get('avoidance',{}),'stop':row['stop']},ensure_ascii=True),flush=True)
                assert row['stop'].get('stationary_confirmed') is True
                assert row['distance_m']<.035 and abs(row['yaw_change_deg'])<4
        except Exception as exc:
            record['error']=str(exc)
        finally:
            try: record['final_stop']=stop()
            except Exception as exc: record['stop_error']=str(exc)
            try:
                post('/api/speed',{'scale':old_speed})
                post('/api/mapping/settings',{'turn_speed':old_turn})
                record['settings_restored']=True
            except Exception as exc: record['restore_error']=str(exc)
            try: record['final']=status()
            except Exception: pass
            (out/'result.json').write_text(json.dumps(record,ensure_ascii=False,indent=2),encoding='utf-8')
            print(json.dumps({'trials':len(record['trials']),'error':record.get('error'),'settings_restored':record.get('settings_restored'),
                              'final_stop':record.get('final_stop')},ensure_ascii=True))


if __name__=='__main__':main()
