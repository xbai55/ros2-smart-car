"""Desktop SSH startup and the existing NetworkManager Wi-Fi worker.

No passwords in argv, local files or logs; remote uploads are private and removed.
"""
import base64
import hashlib
import json
import re
import shlex
import socket
import sys
import time
import uuid
from pathlib import Path

import paramiko


class Cancelled(RuntimeError):
    pass


def resource(name):
    if getattr(sys, 'frozen', False):
        return Path(sys._MEIPASS)/'vehicle'/name
    if name == 'switch_wifi_remote.py':
        return Path(__file__).resolve().parents[2]/'scripts'/name
    return Path(__file__).with_name(name)


def validate_login(user, ssh_port):
    if not re.fullmatch(r'[a-zA-Z_][a-zA-Z0-9_-]{0,31}', user):
        raise ValueError('请填写有效的小车 SSH 用户名')
    if not 1 <= int(ssh_port) <= 65535:
        raise ValueError('SSH 端口须为 1–65535')
    return user, int(ssh_port)


def validate_wifi(ssid, password):
    if not ssid or len(ssid.encode('utf-8')) > 32 or any(c in ssid for c in '\0\r\n'):
        raise ValueError('Wi-Fi 名称须为 1–32 个 UTF-8 字节，不能包含换行')
    if any(c in password for c in '\0\r\n'):
        raise ValueError('Wi-Fi 密码不能包含换行或空字符')
    if not (8 <= len(password) <= 63 and password.isascii()) and not (
        len(password) == 64 and all(c in '0123456789abcdefABCDEF' for c in password)
    ):
        raise ValueError('Wi-Fi 密码须为 8–63 位 ASCII 字符或 64 位十六进制 PSK')


def execute(client, command, input_text=None, timeout=30):
    stdin, stdout, stderr = client.exec_command(command, timeout=timeout)
    if input_text is not None:
        stdin.write(input_text)
        stdin.flush()
    stdin.channel.shutdown_write()
    output = stdout.read().decode('utf-8', 'replace')
    error = stderr.read().decode('utf-8', 'replace')
    return stdout.channel.recv_exit_status(), output, error


class VehicleSession:
    def __init__(self, config, user, password, ssh_port, confirm, progress, cancelled):
        self.config, self.user, self.password = config, user, password
        self.ssh_port = int(ssh_port)
        self.confirm, self.progress, self.cancelled = confirm, progress, cancelled
        self.identity = None

    def check_cancelled(self):
        if self.cancelled.is_set():
            raise Cancelled('已取消。若换网指令已提交，小车仍会完成换网或回退，请重新确认地址。')

    def connect(self, host):
        self.check_cancelled()
        session = self
        known = self.config.root/'known_hosts'

        class ConfirmHost(paramiko.MissingHostKeyPolicy):
            def missing_host_key(self, client, hostname, key):
                digest = base64.b64encode(hashlib.sha256(key.asbytes()).digest()).decode().rstrip('=')
                if session.identity is not None:
                    if key.asbytes() != session.identity:
                        raise RuntimeError('新 IP 对应的 SSH 主机与换网前不同，请核对小车地址')
                elif not session.confirm('确认小车身份', f'首次连接 {host}\n\nSSH 主机指纹\nSHA256:{digest}\n\n确认地址属于你的小车后继续。'):
                    raise Cancelled('未确认小车身份，已取消连接')
                client.get_host_keys().add(hostname, key.get_name(), key)
                client.save_host_keys(str(known))

        client = paramiko.SSHClient()
        client.load_system_host_keys()
        if known.exists():
            client.load_host_keys(str(known))
        client.set_missing_host_key_policy(ConfirmHost())
        try:
            client.connect(host, port=self.ssh_port, username=self.user, password=self.password,
                           look_for_keys=False, allow_agent=False, timeout=5, auth_timeout=8, banner_timeout=8)
            identity = client.get_transport().get_remote_server_key().asbytes()
            if self.identity is not None and self.identity != identity:
                raise RuntimeError('换网后的主机身份不一致，请检查新 IP')
            self.identity = identity
            return client
        except Exception:
            client.close()
            raise

    def api_status(self, client, port):
        code, output, _ = execute(client, 'python3 -c '+shlex.quote(
            "import json,urllib.request;print(urllib.request.urlopen('http://127.0.0.1:"
            +str(int(port))+"/api/status',timeout=2).read().decode())"), timeout=5)
        if code:
            return None
        try:
            result = json.loads(output)
            return result if isinstance(result.get('mode'), str) else None
        except (ValueError, AttributeError):
            return None

    def start(self, host, web_port):
        self.progress('连接小车', '正在验证 SSH 连接与小车身份…')
        with self.connect(host) as client:
            state = self.api_status(client, web_port)
            if state:
                self.progress('小车已在线', '现有智巡服务正在运行，保留当前运行状态。')
                return state
            self.check_cancelled()
            self.progress('启动智巡服务', '正在停止厂家程序并启动已部署的智巡服务…')
            code, output, error = execute(client, 'bash -s', resource('vehicle_start.sh').read_text(encoding='utf-8'), timeout=45)
            if code:
                output += error
                if 'CAR_NOT_DEPLOYED' in output:
                    raise RuntimeError('小车未部署兼容的智巡服务，请先完成小车端部署')
                if 'VENDOR_STILL_RUNNING' in output:
                    raise RuntimeError('厂家程序未退出，已中止启动，避免两个程序同时控制小车')
                if 'CAR_PORT_IN_USE' in output:
                    raise RuntimeError('小车端口被其他程序占用，未启动第二套控制服务')
                raise RuntimeError('小车服务启动失败，请检查小车端服务日志')
            for _ in range(60):
                self.check_cancelled()
                state = self.api_status(client, web_port)
                if state:
                    if state['mode'] != 'stop':
                        raise RuntimeError('新启动的服务未处于停车模式，请在小车端检查后重新连接')
                    return state
                self.progress('等待小车就绪', '服务正在初始化，确认状态接口就绪后打开登录页…')
                if self.cancelled.wait(1):
                    self.check_cancelled()
        raise RuntimeError('小车服务 60 秒内未就绪，请检查小车端日志后重试')

    def wifi_remote(self, client, wifi, status=False):
        directory = '/tmp/smart-car-wifi-'+uuid.uuid4().hex
        with client.open_sftp() as sftp:
            sftp.mkdir(directory, mode=0o700)
            try:
                payload = {key: wifi[key] for key in ('ssid', 'interface', 'hidden')}
                if not status:
                    payload['password'] = wifi['password']
                for name, content in {'helper.py': resource('switch_wifi_remote.py').read_text(encoding='utf-8'),
                                      'config.json': json.dumps(payload, ensure_ascii=False)}.items():
                    path = directory+'/'+name
                    # Set permissions before writing any credential bytes.
                    with sftp.open(path, 'w') as handle:
                        sftp.chmod(path, 0o600)
                        handle.write(content.encode('utf-8'))
                command = 'python3 '+shlex.quote(directory+'/helper.py')+(' --status ' if status else ' --schedule ')+shlex.quote(directory+'/config.json')
                input_text = None
                if not status:
                    code, _, _ = execute(client, 'sudo -n true')
                    command = ('sudo -S -p '+shlex.quote('')+' -- ' if code else 'sudo -n -- ')+command
                    if code:
                        input_text = self.password+'\n'
                code, output, error = execute(client, command, input_text, timeout=90)
                if code:
                    detail = error.strip() or output.strip() or '远程换网请求失败'
                    for secret in (self.password, wifi.get('password')):
                        if secret:
                            detail = detail.replace(secret, '[密码已隐藏]')
                    raise RuntimeError(detail[:450])
                try:
                    return json.loads(output.strip().splitlines()[-1])
                except (ValueError, IndexError):
                    raise RuntimeError('未收到有效的换网结果，请核对小车当前网络') from None
            finally:
                for name in ('helper.py', 'config.json'):
                    try: sftp.remove(directory+'/'+name)
                    except OSError: pass
                try: sftp.rmdir(directory)
                except OSError: pass

    def switch_wifi(self, host, web_port, wifi, ask_address):
        validate_wifi(wifi['ssid'], wifi['password'])
        self.progress('连接小车', '正在确认小车身份与停车状态…')
        with self.connect(host) as client:
            state = self.api_status(client, web_port)
            if state and state['mode'] != 'stop':
                raise RuntimeError('请先在控制台停车并退出当前模式，再更换 Wi-Fi')
            self.check_cancelled()
            self.progress('提交换网任务', '正在保存目标网络；连接失败时小车会尝试恢复原网络…')
            result = self.wifi_remote(client, wifi)
            if result.get('status') != 'scheduled':
                raise RuntimeError('小车未确认换网任务，请检查网络状态')
        new_host = ask_address(host)
        if not new_host:
            raise Cancelled('换网指令已提交。请确认小车的新 IP，再点击连接；尚未验证换网成功。')
        self.progress('确认目标网络', '正在重新连接小车并核对 Wi-Fi；最多等待 90 秒…')
        # The worker starts after five seconds; a submission is never treated as success.
        if self.cancelled.wait(6):
            self.check_cancelled()
        end = time.monotonic()+90
        while time.monotonic() < end:
            self.check_cancelled()
            try:
                with self.connect(new_host) as client:
                    live = self.wifi_remote(client, wifi, status=True)
                    if live.get('matches_target') and live.get('ssid') == wifi['ssid']:
                        return new_host
            except (paramiko.AuthenticationException, paramiko.BadHostKeyException, Cancelled):
                raise
            except (OSError, paramiko.SSHException):
                pass
            if self.cancelled.wait(2):
                self.check_cancelled()
        raise RuntimeError('尚未确认目标 Wi-Fi。请检查电脑是否已连接同一网络、IP 是否正确；小车可能已恢复原网络。')


def friendly_error(exc):
    if isinstance(exc, paramiko.AuthenticationException):
        return '小车 SSH 登录失败，请检查用户名和登录密码（不是网页账户密码）。'
    if isinstance(exc, paramiko.BadHostKeyException):
        return '小车主机指纹发生变化，请确认 IP 是否指向原来的小车。'
    if isinstance(exc, (socket.timeout, TimeoutError)):
        return '连接小车超时，请确认 IP、局域网和 SSH 端口。'
    if isinstance(exc, paramiko.ssh_exception.NoValidConnectionsError):
        return '小车 SSH 端口拒绝连接，请确认小车已开机并启用 SSH。'
    if isinstance(exc, paramiko.SSHException):
        return 'SSH 连接中断或握手失败，请检查小车网络后重试。'
    if isinstance(exc, OSError):
        return '无法连接小车，请检查 IP、网络和 SSH 端口。'
    return str(exc)
