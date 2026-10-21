"""Persistent user data is deliberately outside the program installation."""
import ipaddress
import json
import os
import secrets
import sqlite3
from pathlib import Path
from . import VERSION


def data_directory(override=None):
    return Path(override or os.getenv('INSIGHTROVER_DATA_DIR') or
                Path(os.environ.get('LOCALAPPDATA', Path.home()))/'InsightRover').resolve()


def normalize_address(ip, port=8080):
    ip=str(ip).strip()
    if isinstance(port,bool) or not 1 <= int(port) <= 65535:
        raise ValueError('端口须为 1–65535')
    if not ip:
        return '', int(port)
    address=ipaddress.ip_address(ip)
    return str(address),int(port)


class AppConfig:
    def __init__(self, directory=None):
        self.root=data_directory(directory)
        self.root.mkdir(parents=True,exist_ok=True)
        self.path=self.root/'config.json'
        if self.path.exists():
            self.value=json.loads(self.path.read_text(encoding='utf-8'))
        else:
            self.value={'ip':'','port':8080,'jwt_secret':secrets.token_urlsafe(48),'schema':1}
            self.save()
        self.value['ip'],self.value['port']=normalize_address(self.value.get('ip',''),self.value.get('port',8080))
        if not self.value.get('jwt_secret'):
            raise ValueError('配置中缺少登录密钥，请从备份恢复配置')

    @property
    def car_url(self):
        ip=self.value['ip']
        return f'http://[{ip}]:{self.value["port"]}' if ':' in ip else f'http://{ip}:{self.value["port"]}' if ip else ''

    def save(self):
        temp=self.path.with_suffix('.tmp')
        temp.write_text(json.dumps(self.value,ensure_ascii=False,indent=2),encoding='utf-8')
        os.replace(temp,self.path)

    def set_address(self, ip, port):
        ip,port=normalize_address(ip,port)
        self.value.update(ip=ip,port=port)
        self.save()

    def environment(self):
        env=os.environ.copy()
        for name in ['ALL_PROXY','all_proxy','HTTP_PROXY','http_proxy','HTTPS_PROXY','https_proxy']:
            env.pop(name,None)
        env.update(DATABASE_URL='sqlite:///'+(self.root/'smart_patrol.db').as_posix(),
                   STORAGE_LOCAL_DIR=str(self.root/'storage'),JWT_SECRET=self.value['jwt_secret'],
                   ROBOT_WEB_URL=self.car_url,REDIS_ENABLED='false',MINIO_ENDPOINT='',
                   APP_VERSION=VERSION,NO_PROXY='127.0.0.1,localhost',no_proxy='127.0.0.1,localhost')
        return env

    def has_users(self):
        path=self.root/'smart_patrol.db'
        if not path.exists():return False
        with sqlite3.connect(path.as_uri()+'?mode=ro',uri=True) as db:
            table=db.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='users'").fetchone()
            return bool(table and db.execute('SELECT 1 FROM users LIMIT 1').fetchone())

    def backup_before_upgrade(self, version):
        database=self.root/'smart_patrol.db'
        marker=self.root/'data-version.txt'
        if marker.exists() and marker.read_text(encoding='utf-8')==version:return
        if database.exists():
            import time,shutil
            target=self.root/'backups'/f'before-{version}-{time.time_ns()}'
            target.mkdir(parents=True)
            with sqlite3.connect(database) as source,sqlite3.connect(target/'smart_patrol.db') as destination:
                source.backup(destination)
            shutil.copy2(self.path,target/'config.json')
        # Written only after successful database initialization by the server.
