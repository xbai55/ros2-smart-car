import argparse
import ctypes
import json
import os
import secrets
import socket
import subprocess
import sys
import time
import webbrowser
from pathlib import Path

import httpx
from .config import AppConfig


def resources():
    return Path(sys._MEIPASS)/'web' if getattr(sys,'frozen',False) else Path(__file__).resolve().parents[2]/'web-console/dist'


class BackendProcess:
    def __init__(self,config):
        self.config=config
        self.process=None
        self.token=secrets.token_urlsafe(32)
        self.url=None

    def start(self):
        with socket.socket() as listener:
            try:listener.bind(('127.0.0.1',8765))
            except OSError:listener.bind(('127.0.0.1',0))
            port=listener.getsockname()[1]
        self.url=f'http://127.0.0.1:{port}'
        env=self.config.environment()
        env['INSIGHTROVER_CONTROL_TOKEN']=self.token
        if getattr(sys,'frozen',False):command=[sys.executable]
        else:command=[sys.executable,str(Path(__file__).resolve().parents[1]/'desktop_entry.py')]
        command+=['--serve','--port',str(port),'--data-dir',str(self.config.root)]
        logs=self.config.root/'logs';logs.mkdir(exist_ok=True)
        with (logs/'backend.log').open('ab') as output:
            self.process=subprocess.Popen(command,env=env,stdout=output,stderr=output,stdin=subprocess.DEVNULL,
                    creationflags=subprocess.CREATE_NO_WINDOW if os.name=='nt' else 0)
        try:
            with httpx.Client(trust_env=False,timeout=1) as client:
                end=time.monotonic()+25
                while time.monotonic()<end:
                    if self.process.poll() is not None:raise RuntimeError('后台启动失败，请查看数据目录中的 logs/backend.log')
                    try:
                        if client.get(self.url+'/desktop/health').status_code==200:
                            (self.config.root/'runtime.json').write_text(json.dumps({'url':self.url,'pid':os.getpid()}),encoding='utf-8')
                            return
                    except httpx.HTTPError:pass
                    time.sleep(.2)
            raise RuntimeError('后台启动超时，请查看应用日志')
        except Exception:
            self.stop();raise

    def stop(self):
        if self.process is None:return
        if self.process.poll() is None:
            try:
                with httpx.Client(trust_env=False,timeout=2) as client:
                    client.post(self.url+'/desktop/quit',headers={'X-InsightRover-Token':self.token})
                self.process.wait(timeout=10)
            except (httpx.HTTPError,subprocess.TimeoutExpired):
                self.process.terminate();self.process.wait(timeout=5)
        self.process=None
        (self.config.root/'runtime.json').unlink(missing_ok=True)


def serve(config,port):
    logs=config.root/'logs';logs.mkdir(exist_ok=True)
    if sys.stdout is None:sys.stdout=(logs/'backend.log').open('a',encoding='utf-8')
    if sys.stderr is None:sys.stderr=sys.stdout
    from .server import create_server
    import uvicorn,asyncio
    app=create_server(config,resources(),os.environ.get('INSIGHTROVER_CONTROL_TOKEN',secrets.token_urlsafe(32)))
    server=uvicorn.Server(uvicorn.Config(app,host='127.0.0.1',port=port,log_level='warning',
                access_log=False,loop='asyncio',http='h11',ws='websockets'))
    async def run():
        async def watch():
            while not getattr(app.state,'exit_requested',False):await asyncio.sleep(.2)
            server.should_exit=True
        watcher=asyncio.create_task(watch())
        try:await server.serve()
        finally:
            watcher.cancel();await asyncio.gather(watcher,return_exceptions=True)
    asyncio.run(run())


def gui(config):
    from .desktop_ui import gui as show_gui
    show_gui(config, BackendProcess)


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--serve',action='store_true');parser.add_argument('--port',type=int,default=8765)
    parser.add_argument('--data-dir');parser.add_argument('--initialize-stdin',action='store_true')
    parser.add_argument('--check-gui',action='store_true')
    parser.add_argument('--check-vehicle',action='store_true')
    args=parser.parse_args()
    config=AppConfig(args.data_dir)
    if args.check_vehicle:
        from .vehicle import resource, validate_login
        import paramiko
        validate_login('jetson',22)
        assert resource('vehicle_start.sh').is_file()
        assert resource('switch_wifi_remote.py').is_file()
        (config.root/'vehicle-check.json').write_text(json.dumps({'ssh':True,'wifi_worker':True}),encoding='utf-8')
        return
    if args.check_gui:
        import tkinter as tk
        from .desktop_ui import DesktopWindow
        test=tk.Tk();test.withdraw()
        window=DesktopWindow(test,config,BackendProcess(config),preview=True)
        test.update();window.closed=True;test.destroy()
        (config.root/'gui-check.json').write_text(json.dumps({'tk':True,'version':tk.TkVersion}),encoding='utf-8')
        return
    if args.initialize_stdin:
        from .server import initialize
        initialize(config,json.load(sys.stdin));return
    if args.serve:serve(config,args.port)
    else:gui(config)
