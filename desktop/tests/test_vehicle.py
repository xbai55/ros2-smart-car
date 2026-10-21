"""Real loopback SSH handshake plus startup, identity and Wi-Fi failure contracts."""
import io
import json
import socket
import sys
import threading
import time
from pathlib import Path
from unittest.mock import Mock

import paramiko
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from insightrover_desktop.config import AppConfig
from insightrover_desktop.vehicle import VehicleSession, Cancelled, validate_wifi, validate_login, resource


@pytest.fixture
def ssh_car():
    listener = socket.socket()
    listener.bind(('127.0.0.1', 0))
    listener.listen(8)
    listener.settimeout(.2)
    key = paramiko.RSAKey.generate(2048)
    stop = threading.Event()
    state = {'mode': None, 'started': 0, 'commands': [], 'script': ''}
    transports = []

    class Server(paramiko.ServerInterface):
        def check_auth_password(self, user, password):
            return paramiko.AUTH_SUCCESSFUL if (user, password) == ('jetson', 'test-secret') else paramiko.AUTH_FAILED

        def get_allowed_auths(self, user):
            return 'password'

        def check_channel_request(self, kind, channel):
            return paramiko.OPEN_SUCCEEDED if kind == 'session' else paramiko.OPEN_FAILED_ADMINISTRATIVELY_PROHIBITED

        def check_channel_exec_request(self, channel, command):
            def respond():
                data = b''
                while True:
                    part = channel.recv(65536)
                    if not part:
                        break
                    data += part
                command_text = command.decode()
                state['commands'].append(command_text)
                code = 0
                if command_text == 'bash -s':
                    state['started'] += 1
                    state['script'] = data.decode()
                    state['mode'] = 'stop'
                    channel.sendall(b'CAR_START_REQUESTED\n')
                elif '/api/status' in command_text:
                    if state['mode'] is None:
                        code = 1
                    else:
                        channel.sendall(json.dumps({'mode': state['mode']}).encode())
                else:
                    code = 1
                channel.send_exit_status(code)
                channel.shutdown_write()
                channel.close()
            threading.Thread(target=respond, daemon=True).start()
            return True

    def run():
        while not stop.is_set():
            try:
                conn, _ = listener.accept()
            except socket.timeout:
                continue
            except OSError:
                break
            transport = paramiko.Transport(conn)
            transports.append(transport)
            try:
                transport.add_server_key(key)
                transport.start_server(server=Server())
            except (paramiko.SSHException, EOFError):
                transport.close()
    thread = threading.Thread(target=run, daemon=True)
    thread.start()
    yield listener.getsockname()[1], state, key
    stop.set()
    listener.close()
    for transport in transports:
        transport.close()
    thread.join(2)


def session(tmp_path, port, confirm=lambda *args: True):
    return VehicleSession(AppConfig(tmp_path), 'jetson', 'test-secret', port, confirm, Mock(), threading.Event())


def test_real_ssh_start_and_existing_task_preserved(tmp_path, ssh_car):
    port, state, _ = ssh_car
    confirmation = Mock(return_value=True)
    remote = session(tmp_path, port, confirmation)
    assert remote.start('127.0.0.1', 8080)['mode'] == 'stop'
    assert state['started'] == 1
    assert 'pkill -INT' in state['script']
    assert 'systemctl --user start' in state['script']
    assert 'enable --now' not in state['script']
    assert 'hidden=true' not in state['script'].lower()
    assert not any('test-secret' in command for command in state['commands'])
    assert 'test-secret' not in (tmp_path/'known_hosts').read_text()
    assert confirmation.call_count == 1
    state['mode'] = 'patrol'
    assert remote.start('127.0.0.1', 8080)['mode'] == 'patrol'
    assert state['started'] == 1
    assert confirmation.call_count == 1


def test_declined_identity_never_starts_car(tmp_path, ssh_car):
    port, state, _ = ssh_car
    with pytest.raises(Cancelled):
        session(tmp_path, port, lambda *args: False).start('127.0.0.1', 8080)
    assert state['started'] == 0 and state['commands'] == []


def test_wrong_password_never_starts_car(tmp_path, ssh_car):
    port, state, _ = ssh_car
    remote = session(tmp_path, port)
    remote.password = 'wrong'
    with pytest.raises(paramiko.AuthenticationException):
        remote.start('127.0.0.1', 8080)
    assert state['started'] == 0


def test_cancel_before_connection(tmp_path):
    remote = session(tmp_path, 22)
    remote.cancelled.set()
    with pytest.raises(Cancelled):
        remote.start('192.0.2.1', 8080)


def test_wifi_refuses_active_task_before_schedule(tmp_path, ssh_car):
    port, state, _ = ssh_car
    state['mode'] = 'manual'
    remote = session(tmp_path, port)
    remote.wifi_remote = Mock()
    with pytest.raises(RuntimeError, match='先在控制台停车'):
        remote.switch_wifi('127.0.0.1', 8080, dict(ssid='lab', password='wifi-secret'), Mock())
    remote.wifi_remote.assert_not_called()


def test_wifi_cancel_after_submission_is_not_success(tmp_path, ssh_car):
    port, state, _ = ssh_car
    state['mode'] = 'stop'
    remote = session(tmp_path, port)
    remote.wifi_remote = Mock(return_value={'status': 'scheduled'})
    with pytest.raises(Cancelled, match='尚未验证换网成功'):
        remote.switch_wifi('127.0.0.1', 8080, dict(ssid='lab', password='wifi-secret'), lambda old: None)


def test_wifi_submission_requires_live_ssid_verification(tmp_path, ssh_car):
    port, state, _ = ssh_car
    state['mode'] = 'stop'
    remote = session(tmp_path, port)
    remote.cancelled = Mock(is_set=Mock(return_value=False), wait=Mock(return_value=False))
    remote.wifi_remote = Mock(side_effect=[{'status': 'scheduled'}, {'matches_target': False, 'ssid': 'old'}, {'matches_target': True, 'ssid': 'lab'}])
    assert remote.switch_wifi('127.0.0.1', 8080, dict(ssid='lab', password='wifi-secret'), lambda old: old) == '127.0.0.1'
    assert remote.wifi_remote.call_count == 3


@pytest.mark.parametrize('ssid,password', [('', 'wifi-secret'), ('lab\n', 'wifi-secret'), ('lab', 'short'), ('lab', '不允许的密码长度')])
def test_wifi_validation(ssid, password):
    with pytest.raises(ValueError):
        validate_wifi(ssid, password)


def test_resource_and_login_contract():
    assert resource('switch_wifi_remote.py').exists()
    assert resource('vehicle_start.sh').exists()
    with pytest.raises(ValueError):
        validate_login('jetson; rm', 22)


def test_wifi_cleanup_and_secret_redaction(tmp_path, monkeypatch):
    from unittest.mock import MagicMock
    from insightrover_desktop import vehicle
    remote = session(tmp_path, 22)
    client = MagicMock()
    sftp = client.open_sftp.return_value.__enter__.return_value
    monkeypatch.setattr(vehicle, 'execute', Mock(side_effect=[(0, '', ''), (1, '', 'Failure wifi-secret test-secret')]))
    with pytest.raises(RuntimeError) as failure:
        remote.wifi_remote(client, dict(ssid='lab', password='wifi-secret', hidden=False, interface=''))
    assert 'wifi-secret' not in str(failure.value)
    assert 'test-secret' not in str(failure.value)
    assert sftp.mkdir.call_args.kwargs['mode'] == 0o700
    assert all(call.args[1] == 0o600 for call in sftp.chmod.call_args_list)
    assert sftp.remove.call_count == 2
    sftp.rmdir.assert_called_once()
    # Credential bytes travel only through the private SFTP files, never command arguments.
    assert all('wifi-secret' not in call.args[1] for call in vehicle.execute.call_args_list)
