"""Isolated real-API editor acceptance fixture. No ROS or vehicle connection."""
import json
import os
from pathlib import Path
import sys
from uuid import uuid4

ROOT=Path(__file__).resolve().parents[1]
OUTPUT=ROOT/'output/map-editor-20261019'
OUTPUT.mkdir(exist_ok=True,parents=True)
os.environ['DATABASE_URL']='sqlite:///'+(OUTPUT/f'browser-{uuid4().hex}.sqlite3').as_posix()
os.environ['JWT_SECRET']='local-map-editor-test-only'
sys.path.insert(0,str(ROOT/'backend'))
from fastapi import FastAPI, WebSocket
from fastapi.staticfiles import StaticFiles
from app.api.router import api_router
from app.db.session import engine,SessionLocal
from app.db.base import Base
from app.seed import seed_session
from app.models import MapModel
from app.services import storage
from app.services.slam_maps import snapshot_assets
from app.gateway.robot_gateway import RobotGateway


def app():
    Base.metadata.create_all(engine)
    storage._storage=storage.LocalStorageService(str(OUTPUT/'browser-storage'))
    snapshot={'header':{'frame_id':'map'},'session_id':'isolated-editor','revision':1,
              'info':{'width':160,'height':100,'resolution':.05,'origin':{'x':0,'y':0,'yaw':0}},'data':[0]*16000,'keepout':[0]*16000}
    for y in range(100):
        for x in range(160):
            if x<3 or x>156 or y<3 or y>96:snapshot['data'][y*160+x]=100
    for x,y in [(40,30),(60,50),(100,70)]:snapshot['data'][y*160+x]=100
    snapshot['keepout'][40*160+120]=100
    packed=snapshot_assets(snapshot);assets={}
    for n,(content,mime) in packed['assets'].items():
        key=f'maps/editor-fixture/{packed["digest"]}/{n}';storage.get_storage().put(key,content,content_type=mime);assets[n]=key
    with SessionLocal() as db:
        seed_session(db)
        db.add(MapModel(id='editor-fixture',name='编辑验证地图（隔离测试）',width=160,height=100,resolution=.05,origin='[0,0,0]',active=True,image_key=assets['preview.png'],
                        meta=json.dumps({'source':'slam','assets':assets,'digest':packed['digest'],'session_id':'isolated-editor'})))
        db.commit()
    async def no_vehicle(*args,**kwargs):raise RuntimeError('隔离编辑验证不连接小车')
    RobotGateway.navigation_request=no_vehicle
    api=FastAPI();api.include_router(api_router)
    @api.get('/api/status')
    def offline_status():return {'simulation':True,'mode':'stop','updated_at':0}
    @api.websocket('/ws/status')
    async def offline_socket(socket: WebSocket):
        import asyncio
        await socket.accept()
        try:
            while True:
                await socket.send_json({'simulation':True,'mode':'stop','updated_at':0})
                await asyncio.sleep(2)
        except Exception:pass
    api.mount('/',StaticFiles(directory=ROOT/'web-console/dist',html=True),name='web')
    return api


if __name__=='__main__':
    import uvicorn
    uvicorn.run(app(),host='127.0.0.1',port=8111)
