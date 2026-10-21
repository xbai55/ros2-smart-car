"""Isolated operator-settings UI fixture; no ROS or real vehicle connection."""
import sys
import time
from pathlib import Path
from uuid import uuid4

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/'ros2_ws/src/smart_car_decision'))
from conftest import FakeWebNode
from smart_car_decision.mapping_settings import MappingSettings
from smart_car_decision.web_api import create_app


def app():
    node=FakeWebNode(ros_status_age_sec=.01)
    node.motion_settings=MappingSettings()
    node.store.update(mode='mapping', lidar={'ok':True}, odom={'ok':True}, tf={'ok':True},
                      map={'ok':True,'width':40,'height':40,'resolution':.05},
                      map_pose={'ok':True,'x':0,'y':0,'yaw':0}, manual_turn_speed=.15, speed_scale=.35)
    state={'session_id':'qa-initial','state':'ready','started_at':time.time(),'error':None,'max_laser_range':6.}
    class Restart:
        def snapshot(self): return {**state,'configured_max_laser_range':node.motion_settings.snapshot()['max_laser_range']}
        def restart(self):
            state.update(session_id=uuid4().hex, max_laser_range=node.motion_settings.snapshot()['max_laser_range'])
            node.map_snapshot._snapshot['session_id']=state['session_id']
            return {'ok':True,'pid':0,'mapping':self.snapshot(),'session_id':state['session_id']}
    node.mapping_restart=Restart()
    def settings(changes):
        result=node.motion_settings.update(**changes)
        node.store.update(manual_turn_speed=result['turn_speed'])
        return result
    node.set_motion_settings=settings
    data=[0]*1600
    for y in range(40):
        for x in range(40):
            if x in (0,39) or y in (0,39): data[y*40+x]=100
    node.map_snapshot.update({'session_id':state['session_id'],'revision':1,'updated_at':time.time(),
                             'header':{'frame_id':'map','stamp':{'sec':1,'nanosec':0}},
                             'info':{'width':40,'height':40,'resolution':.05,'origin':{'x':-1,'y':-1,'yaw':0}},'data':data})
    return create_app(node, static_dir=ROOT/'web-console/dist')


if __name__=='__main__':
    import uvicorn
    uvicorn.run(app(),host='127.0.0.1',port=8113,log_level='warning')
