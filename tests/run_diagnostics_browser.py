"""Exercise the built console against an isolated production diagnostic API."""
import socket
import subprocess
import sys
import time
from pathlib import Path
from urllib.error import URLError
from urllib.request import urlopen

from playwright.sync_api import expect, sync_playwright

ROOT = Path(__file__).resolve().parents[1]


def check(url):
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(channel='chrome', headless=True)
        operator = browser.new_page()
        operator.goto(url + '/#/login')
        operator.get_by_label('用户名').fill('operator')
        operator.get_by_label('密码').fill('operator123')
        operator.get_by_role('button', name='进入工作台').click()
        operator.wait_for_url('**/#/')
        operator.goto(url + '/#/system/diagnostics')
        expect(operator.get_by_role('heading', name='日志与诊断')).to_be_visible()
        operator.get_by_role('button', name='控制器已发布零速度 · 控制租约到期').click()
        expect(operator.get_by_label('日志详情').get_by_text('停车后里程计确认静止', exact=False).first).to_be_visible()
        expect(operator.get_by_role('button', name='导出诊断包')).to_have_count(0)
        operator.get_by_role('button', name='关闭详情').click()
        operator.get_by_role('button', name='暂停实时更新').click()
        expect(operator.get_by_role('button', name='恢复实时更新')).to_be_visible()
        operator.get_by_role('button', name='恢复实时更新').click()
        operator.route('**/diagnostics/stops?*', lambda route: route.abort())
        expect(operator.get_by_text('正在等待重连', exact=False)).to_be_visible(timeout=10000)
        operator.unroute('**/diagnostics/stops?*')
        expect(operator.get_by_text('正在等待重连', exact=False)).to_have_count(0, timeout=12000)
        operator.get_by_label('关键词').fill('control_lease_expired')
        operator.get_by_role('button', name='应用筛选').click()
        expect(operator.get_by_role('button', name='控制器已发布零速度 · 控制租约到期')).to_be_visible()
        operator.goto(url + '/#/system/diagnostics/executions/fixture-execution')
        expect(operator.get_by_text('助手模型调用结束', exact=False)).to_be_visible()
        expect(operator.get_by_text('execution.failed', exact=False)).to_be_visible()
        admin = browser.new_page()
        admin.goto(url + '/#/login')
        admin.get_by_label('用户名').fill('admin')
        admin.get_by_label('密码').fill('admin123')
        admin.get_by_role('button', name='进入工作台').click()
        admin.wait_for_url('**/#/')
        admin.goto(url + '/#/system/diagnostics/executions/fixture-execution')
        expect(admin.get_by_role('alert')).to_contain_text('执行不存在')
        admin.goto(url + '/#/system/diagnostics')
        with admin.expect_download() as result:
            admin.get_by_role('button', name='导出诊断包').click()
        assert result.value.suggested_filename.endswith('.zip')
        browser.close()


if __name__ == '__main__':
    with socket.socket() as listener:
        listener.bind(('127.0.0.1', 0))
        port = listener.getsockname()[1]
    url = f'http://127.0.0.1:{port}'
    with subprocess.Popen([sys.executable, str(ROOT / 'tests/diagnostics_browser_fixture.py'), str(port)]) as server:
        try:
            for _ in range(100):
                try:
                    with urlopen(url, timeout=.2):
                        break
                except (URLError, TimeoutError):
                    if server.poll() is not None:
                        raise RuntimeError('Fixture failed to start')
                    time.sleep(.1)
            else:
                raise RuntimeError('Fixture timed out')
            check(url)
            print('Browser diagnostics acceptance passed')
        finally:
            server.terminate()
