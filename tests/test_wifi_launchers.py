"""Offline checks for Wi-Fi scheduling, rollback, secrets, and local validation."""
import contextlib
import importlib.util
import io
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[2]
TEST_TEMP = ROOT / 'output' / 'wifi-launcher-20261014' / 'test-temp'
sys.path.insert(0, str(ROOT))
import startup_wifi as local

spec = importlib.util.spec_from_file_location("wifi_remote", ROOT / "ros2-smart-car/scripts/switch_wifi_remote.py")
remote = importlib.util.module_from_spec(spec)
spec.loader.exec_module(remote)


def config(**overrides):
    value = dict(ssid="测试热点 '$() ;", password="abc'$();1234", interface="", hidden=False, ssh_user="jetson")
    value.update(overrides)
    return value


class LocalChecks(unittest.TestCase):
    def setUp(self):
        TEST_TEMP.mkdir(parents=True, exist_ok=True)

    def load(self, value):
        with tempfile.TemporaryDirectory(dir=TEST_TEMP) as directory:
            path = Path(directory) / "config.json"
            path.write_text(json.dumps(value, ensure_ascii=False), encoding="utf-8-sig")
            return local.load_config(path)

    def test_special_characters_preserved(self):
        self.assertEqual(self.load(config()), config())

    def test_invalid_configuration_rejected(self):
        for change in (dict(ssid="填写目标WiFi名称"), dict(password="short"),
                       dict(hidden="false"), dict(ssid="汉" * 11), dict(password="abcd\n1234")):
            with self.subTest(change=change), self.assertRaises(ValueError):
                self.load(config(**change))

    def test_check_config_does_not_connect_or_print_password(self):
        with tempfile.TemporaryDirectory(dir=TEST_TEMP) as directory:
            path = Path(directory) / "config.json"
            path.write_text(json.dumps(config()), encoding="utf-8")
            output = io.StringIO()
            with patch.object(local, "connect") as connection, patch.object(local, "load_car_ip", return_value="192.0.2.1"), contextlib.redirect_stdout(output):
                self.assertEqual(local.main(["--config", str(path), "--check-config"]), 0)
            connection.assert_not_called()
            self.assertNotIn(config()["password"], output.getvalue())

    def test_password_login_when_no_keys_exist(self):
        import paramiko
        client = Mock()
        client.connect.side_effect = [paramiko.SSHException("No authentication methods available"), None]
        with patch.object(paramiko, "SSHClient", return_value=client), patch.object(local.getpass, "getpass", return_value="login-secret"):
            connection, password = local.connect("192.0.2.1", "jetson")
        self.assertIs(connection, client)
        self.assertEqual(password, "login-secret")
        self.assertEqual(client.connect.call_args.kwargs["password"], "login-secret")

    def test_host_key_mismatch_does_not_prompt_for_password(self):
        import paramiko
        client = Mock()
        key = Mock()
        key.get_base64.return_value = "key"
        client.connect.side_effect = paramiko.BadHostKeyException("192.0.2.1", key, key)
        with patch.object(paramiko, "SSHClient", return_value=client), patch.object(local.getpass, "getpass") as prompt:
            with self.assertRaisesRegex(RuntimeError, "指纹"):
                local.connect("192.0.2.1", "jetson")
        prompt.assert_not_called()

    def test_sftp_secrets_not_in_local_remote_command_and_cleanup(self):
        sftp = Mock()
        sftp.__enter__ = Mock(return_value=sftp)
        sftp.__exit__ = Mock(return_value=False)
        handle = Mock()
        handle.__enter__ = Mock(return_value=handle)
        handle.__exit__ = Mock(return_value=False)
        sftp.open.return_value = handle
        client = Mock()
        client.open_sftp.return_value = sftp
        result = dict(status="scheduled", ssid=config()["ssid"], unit="test")
        with patch.object(local, "execute", side_effect=[(1, "", ""), (0, json.dumps(result), "")]) as execute:
            self.assertEqual(local.run_remote(client, config(), "login-secret"), result)
        command = execute.call_args.args[1]
        self.assertNotIn(config()["password"], command)
        self.assertNotIn("login-secret", command)
        self.assertEqual(execute.call_args.args[2], "login-secret\n")
        self.assertEqual(sftp.remove.call_count, 2)
        sftp.rmdir.assert_called_once()


class RemoteChecks(unittest.TestCase):
    def setUp(self):
        TEST_TEMP.mkdir(parents=True, exist_ok=True)

    def test_networkmanager_error_keeps_reason_and_redacts_password(self):
        failure = Mock(returncode=1, stderr="Error: rejected psk " + config()["password"], stdout="")
        with patch.object(remote.subprocess, "run", return_value=failure):
            with self.assertRaises(RuntimeError) as caught:
                remote.nm("connection", "add", "802-11-wireless-security.psk", config()["password"])
        self.assertIn("rejected psk", str(caught.exception))
        self.assertIn("[密码已隐藏]", str(caught.exception))
        self.assertNotIn(config()["password"], str(caught.exception))

    def test_ambiguous_or_missing_interface_rejected(self):
        with patch.object(remote, "nm", return_value="wlan0:wifi\nwlan1:wifi\neth0:ethernet"):
            with self.assertRaises(RuntimeError):
                remote.interface_for(config())
            with self.assertRaises(RuntimeError):
                remote.interface_for(config(interface="missing"))
            self.assertEqual(remote.interface_for(config(interface="wlan1")), "wlan1")

    def test_status_confirms_actual_ssid_and_ipv4(self):
        with patch.object(remote, "interface_for", return_value="wlan0"), patch.object(remote, "current_uuid", return_value="active"), patch.object(remote, "nm", side_effect=["other-wifi", "192.0.2.2/24"]):
            self.assertFalse(remote.status(config())["matches_target"])
        with patch.object(remote, "interface_for", return_value="wlan0"), patch.object(remote, "current_uuid", return_value="active"), patch.object(remote, "nm", side_effect=[config()["ssid"], "192.0.2.2/24"]):
            self.assertTrue(remote.status(config())["matches_target"])

    def test_schedule_uses_fresh_profile_and_secret_free_background_job(self):
        with tempfile.TemporaryDirectory(dir=TEST_TEMP) as directory:
            job_dir = Path(directory) / "private-job"
            job_dir.mkdir()
            with patch.object(remote.os, "geteuid", return_value=0, create=True), patch.object(remote.shutil, "which", return_value="tool"), patch.object(remote, "interface_for", return_value="wlan0"), patch.object(remote, "current_uuid", return_value="old-uuid"), patch.object(remote.tempfile, "mkdtemp", return_value=str(job_dir)), patch.object(remote, "nm", return_value="new-uuid") as nm, patch.object(remote.subprocess, "run", return_value=Mock(returncode=0)) as run:
                result = remote.schedule(config())
            self.assertEqual(result["status"], "scheduled")
            job = json.loads((job_dir / "job.json").read_text(encoding="utf-8"))
            self.assertEqual(job["previous"], "old-uuid")
            self.assertNotEqual(job["target"], "old-uuid")
            self.assertNotIn("password", job)
            self.assertNotIn(config()["password"], str(run.call_args))
            self.assertIn("--on-active=5s", run.call_args.args[0])
            add_args = nm.call_args_list[0].args
            self.assertIn(config()["password"], add_args)
            self.assertNotIn("connection.uuid", add_args)
            self.assertEqual(job["target"], "new-uuid")

    def test_schedule_failure_removes_new_profile(self):
        with tempfile.TemporaryDirectory(dir=TEST_TEMP) as directory:
            job_dir = Path(directory) / "private-job"
            job_dir.mkdir()
            with patch.object(remote.os, "geteuid", return_value=0, create=True), patch.object(remote.shutil, "which", return_value="tool"), patch.object(remote, "interface_for", return_value="wlan0"), patch.object(remote, "current_uuid", return_value="old-uuid"), patch.object(remote.tempfile, "mkdtemp", return_value=str(job_dir)), patch.object(remote, "nm", return_value="new-uuid") as nm, patch.object(remote.subprocess, "run", return_value=Mock(returncode=1)):
                with self.assertRaisesRegex(RuntimeError, "未开始切换"):
                    remote.schedule(config())
            self.assertEqual(nm.call_args.args[:3], ("connection", "delete", "uuid"))
            self.assertFalse(job_dir.exists())

    def activate(self, side_effect=None, active="new", previous="old"):
        with tempfile.TemporaryDirectory(dir=TEST_TEMP) as directory:
            job_dir = Path(directory) / "worker"
            job_dir.mkdir()
            job_path = job_dir / "job.json"
            helper = job_dir / "worker.py"
            job_path.touch()
            helper.touch()
            with patch.object(remote, "__file__", str(helper)), patch.object(remote, "nm", side_effect=side_effect) as nm, patch.object(remote, "current_uuid", return_value=active), contextlib.redirect_stdout(io.StringIO()):
                code = remote.activate(dict(interface="wlan0", target="new", previous=previous), job_path)
            self.assertFalse(job_dir.exists())
            return code, [call.args for call in nm.call_args_list]

    def test_activation_success_enables_autoconnect(self):
        code, calls = self.activate()
        self.assertEqual(code, 0)
        self.assertIn(("connection", "modify", "uuid", "new", "connection.autoconnect", "yes", "connection.autoconnect-priority", "20"), calls)
        self.assertFalse(any("old" in call for call in calls))

    def test_activation_failure_restores_old_and_deletes_failed_profile(self):
        code, calls = self.activate([RuntimeError("failed"), "", ""])
        self.assertEqual(code, 1)
        self.assertIn(("--wait", "30", "connection", "up", "uuid", "old", "ifname", "wlan0"), calls)
        self.assertIn(("connection", "delete", "uuid", "new"), calls)

    def test_success_command_but_wrong_active_profile_rolls_back(self):
        code, calls = self.activate(active="other")
        self.assertEqual(code, 1)
        self.assertTrue(any("old" in call for call in calls))

    def test_no_previous_connection_reports_failure(self):
        code, calls = self.activate([RuntimeError("failed"), ""], previous="")
        self.assertEqual(code, 1)
        self.assertFalse(any("--wait" in call and "30" in call for call in calls))


if __name__ == "__main__":
    unittest.main()
