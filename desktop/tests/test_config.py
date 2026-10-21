import json
import sqlite3
import sys
from pathlib import Path

import pytest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from insightrover_desktop.config import AppConfig,normalize_address


@pytest.mark.parametrize('ip,port',[('192.168.1.106',8080),('127.0.0.1',9000),('::1',8080),('',8080)])
def test_address_normalization(ip,port):
    assert normalize_address(ip,port)==(ip,port)


@pytest.mark.parametrize('ip,port',[('http://192.168.1.2',8080),('bad',8080),('127.0.0.1',0),('',65536),('127.0.0.1',True)])
def test_invalid_address_rejected(ip,port):
    with pytest.raises(ValueError):normalize_address(ip,port)


def test_config_secret_and_map_files_survive_upgrade(tmp_path):
    cfg=AppConfig(tmp_path/'用户数据')
    cfg.set_address('192.168.1.106',8080)
    secret=cfg.value['jwt_secret']
    assert len(secret)>32
    assert AppConfig(cfg.root).value['jwt_secret']==secret
    assert cfg.environment()['DATABASE_URL'].endswith('用户数据/smart_patrol.db')
    assert cfg.car_url=='http://192.168.1.106:8080'
    storage=cfg.root/'storage/maps';storage.mkdir(parents=True)
    (storage/'map.pgm').write_bytes(b'original-map-bytes')
    with sqlite3.connect(cfg.root/'smart_patrol.db') as db:
        db.execute('CREATE TABLE users (id TEXT)');db.execute("INSERT INTO users VALUES ('retained')")
    (cfg.root/'data-version.txt').write_text('0.2.0')
    cfg.backup_before_upgrade('0.3.0')
    backups=list((cfg.root/'backups').glob('*/smart_patrol.db'))
    assert len(backups)==1
    with sqlite3.connect(backups[0]) as db:assert db.execute('SELECT id FROM users').fetchone()[0]=='retained'
    assert json.loads((backups[0].parent/'config.json').read_text())['jwt_secret']==secret
    assert (storage/'map.pgm').read_bytes()==b'original-map-bytes'
    assert cfg.has_users()


def test_no_user_data_or_credentials_in_application_payload():
    root=Path(__file__).resolve().parents[2]
    package=root/'output/windows-app-20261020/dist/InsightRover'
    if not package.exists():pytest.skip('frozen build not present')
    forbidden={'smart_patrol.db','smart_patrol.db-wal','key.txt','motion-mapping.json','config.json','小车IP.txt'}
    assert not [p for p in package.rglob('*') if p.name in forbidden]
