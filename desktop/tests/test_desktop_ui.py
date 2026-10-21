"""Exercise real native widgets with a stub vehicle, without contacting hardware."""
import sys
import time
import tkinter as tk
import pytest
from pathlib import Path
from unittest.mock import Mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from insightrover_desktop.config import AppConfig
from insightrover_desktop import desktop_ui as ui


@pytest.fixture(scope='module')
def tk_app():
    app = tk.Tk()
    app.withdraw()
    yield app
    app.destroy()


def test_startup_guide_and_wifi_flow(tmp_path, monkeypatch, tk_app):
    root = tk.Toplevel(tk_app)
    root.withdraw()
    config = AppConfig(tmp_path)
    backend = Mock(process=None, url='http://127.0.0.1:12345')
    monkeypatch.setattr(ui, 'create_admin', lambda *args: True)
    browser = Mock()
    monkeypatch.setattr(ui.webbrowser, 'open', browser)
    vehicle = Mock()
    vehicle.start.return_value = {'mode': 'stop'}
    vehicle.switch_wifi.return_value = '192.0.2.2'
    monkeypatch.setattr(ui, 'VehicleSession', Mock(return_value=vehicle))
    window = ui.DesktopWindow(root, config, backend)
    try:
        window.ip.set('192.0.2.1')
        window.password.set('only-in-memory')
        window.begin()
        deadline = time.monotonic()+3
        while window.busy and time.monotonic() < deadline:
            root.update()
            time.sleep(.02)
        assert not window.busy
        vehicle.start.assert_called_once_with('192.0.2.1', 8080)
        vehicle.switch_wifi.assert_not_called()
        browser.assert_called_once_with('http://127.0.0.1:12345/#/slam')
        assert '控制台已打开' in window.status_title.get()
        assert window.password.get() == ''
        assert 'only-in-memory' not in config.path.read_text()
        window.change_wifi.set('yes')
        window.toggle_wifi()
        window.ssid.set('lab')
        window.wifi_password.set('wifi-password')
        window.begin()
        deadline = time.monotonic()+3
        while window.busy and time.monotonic() < deadline:
            root.update()
            time.sleep(.02)
        assert not window.busy
        vehicle.switch_wifi.assert_called_once()
        vehicle.start.assert_called_with('192.0.2.2', 8080)
        assert config.value['ip'] == '192.0.2.2'
        assert 'wifi-password' not in config.path.read_text()
        assert window.wifi_password.get() == ''
    finally:
        window.closed = True
        root.destroy()


def test_validation_does_not_start_network(tmp_path, monkeypatch, tk_app):
    root = tk.Toplevel(tk_app)
    root.withdraw()
    network = Mock()
    monkeypatch.setattr(ui, 'VehicleSession', network)
    window = ui.DesktopWindow(root, AppConfig(tmp_path), Mock(process=None))
    try:
        window.begin()
        assert not window.busy
        assert '请填写小车当前 IP' == window.status_detail.get()
        network.assert_not_called()
    finally:
        window.closed = True
        root.destroy()
