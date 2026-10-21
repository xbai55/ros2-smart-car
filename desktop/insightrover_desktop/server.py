import asyncio
import os
import re
from pathlib import Path
from uuid import uuid4

import httpx
from fastapi import HTTPException, Request, WebSocket
from fastapi.responses import StreamingResponse
from fastapi.staticfiles import StaticFiles

CAR_PATH=re.compile(r'^(status|map|video|mode|command|emergency-stop|speed|mode-obstacle-stop-distance|mapping/[\w/-]+|navigation/[\w/-]+)$')


def initialize(config, admin=None):
    os.environ.update(config.environment())
    from . import VERSION
    config.backup_before_upgrade(VERSION)
    from app.db.base import Base
    from app.db.session import engine,SessionLocal
    from app.db.migrate import ensure_schema
    from app.models import User,Role,Robot,AppSetting
    from app.core.security import hash_password
    from app.seed import seed_session
    Base.metadata.create_all(engine)
    ensure_schema(engine)
    with SessionLocal() as db:
        # Never seed demo accounts or rewrite roles on a normal launch.
        if not db.query(User).first():
            if not admin:raise ValueError('首次使用请先设置管理员账户')
            username,password=admin['username'],admin['password']
            if not re.fullmatch(r'[A-Za-z0-9_-]{3,64}',username) or not 8<=len(password)<=128:
                raise ValueError('用户名须为 3–64 位字母、数字、下划线；密码至少 8 位')
            seed_session(db,users={})
            user=User(id=str(uuid4()),username=username,password_hash=hash_password(password),display_name='管理员',active=True)
            user.roles=[db.query(Role).filter(Role.name=='admin').one()]
            db.add(user)
        if not db.get(Robot,'r-001'):
            db.add(Robot(id='r-001',name='智巡一号',serial='r-001'))
        address=db.query(AppSetting).filter(AppSetting.key=='robot_web_url').one_or_none()
        if address is None:db.add(AppSetting(id=str(uuid4()),key='robot_web_url',value=config.car_url))
        else:address.value=config.car_url
        db.commit()
    (config.root/'data-version.txt').write_text(VERSION,encoding='utf-8')


def create_server(config, web_root, token, admin=None):
    initialize(config,admin)
    from app.main import app
    from app.db.session import SessionLocal
    from app.models import AppSetting

    def target():
        with SessionLocal() as db:
            value=db.query(AppSetting).filter(AppSetting.key=='robot_web_url').one_or_none()
            return (value.value if value else config.car_url).rstrip('/')

    @app.get('/desktop/health')
    def health():
        return {'status':'ready','version':'0.3.0','ip':config.value['ip']}

    @app.post('/desktop/quit')
    def quit_server(request:Request):
        if request.headers.get('X-InsightRover-Token')!=token:
            raise HTTPException(403,'无效的本机管理请求')
        app.state.exit_requested=True
        return {'ok':True}

    async def forward(request,path):
        base=target()
        if not base:raise HTTPException(503,'请在应用窗口中配置小车 IP')
        headers={k:v for k,v in request.headers.items() if k.lower() not in {'host','connection','content-length'}}
        client=httpx.AsyncClient(trust_env=False,timeout=httpx.Timeout(60,connect=4))
        try:
            upstream=await client.send(client.build_request(request.method,base+path,
                        params=request.query_params,headers=headers,content=await request.body()),stream=True)
        except httpx.HTTPError:
            await client.aclose()
            raise HTTPException(502,'无法连接小车，请检查 IP 和局域网连接') from None
        async def body():
            try:
                async for chunk in upstream.aiter_raw():yield chunk
            finally:
                await upstream.aclose();await client.aclose()
        response_headers={k:v for k,v in upstream.headers.items() if k.lower() not in {'transfer-encoding','connection'}}
        return StreamingResponse(body(),status_code=upstream.status_code,headers=response_headers)

    @app.api_route('/api/{path:path}',methods=['GET','POST','PUT','DELETE','PATCH','OPTIONS'])
    async def car_api(path:str,request:Request):
        if not CAR_PATH.fullmatch(path) or '..' in path:raise HTTPException(404,'接口不存在')
        return await forward(request,'/api/'+path)

    @app.get('/video_feed')
    async def video(request:Request):return await forward(request,'/video_feed')

    @app.websocket('/ws/status')
    async def status_socket(socket:WebSocket):
        from websockets.legacy.client import connect
        await socket.accept()
        base=target()
        if not base:
            await socket.close(code=1013);return
        try:
            async with connect(base.replace('http://','ws://').replace('https://','wss://')+'/ws/status',open_timeout=4,max_size=8*1024*1024) as upstream:
                async def send():
                    async for message in upstream:
                        if isinstance(message,bytes):await socket.send_bytes(message)
                        else:await socket.send_text(message)
                async def receive():
                    while True:await upstream.send(await socket.receive_text())
                tasks=[asyncio.create_task(send()),asyncio.create_task(receive())]
                try:
                    done,pending=await asyncio.wait(tasks,return_when=asyncio.FIRST_COMPLETED)
                    for task in done:task.result()
                finally:
                    for task in tasks:task.cancel()
                    await asyncio.gather(*tasks,return_exceptions=True)
        except Exception:
            try:await socket.close(code=1013)
            except RuntimeError:pass

    app.mount('/',StaticFiles(directory=Path(web_root),html=True),name='desktop-web')
    return app
