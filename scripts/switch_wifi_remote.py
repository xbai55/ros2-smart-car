#!/usr/bin/env python3
"""Uploaded by startup_wifi.py. Uses NetworkManager; never prints credentials."""
import json
import os
import shutil
import subprocess
import sys
import tempfile
import uuid
from pathlib import Path


def nm(*args, timeout=20):
    result = subprocess.run(["nmcli", *args], stdout=subprocess.PIPE,
                            stderr=subprocess.PIPE, encoding="utf-8", timeout=timeout,
                            env=dict(os.environ, LC_ALL="C"))
    if result.returncode:
        detail = result.stderr.strip() or "未返回具体原因。"
        # Keep the actual diagnostic but never echo a supplied PSK.
        for index, argument in enumerate(args[:-1]):
            if argument.endswith(".psk") and args[index + 1]:
                detail = detail.replace(args[index + 1], "[密码已隐藏]")
        raise RuntimeError("NetworkManager 操作失败：" + detail)
    return result.stdout.strip()


def interface_for(config):
    devices = [line.rsplit(":", 1)[0] for line in nm("-t", "-f", "DEVICE,TYPE", "device", "status").splitlines()
               if line.rsplit(":", 1)[-1] == "wifi"]
    iface = config.get("interface", "")
    if not iface:
        if len(devices) != 1:
            raise RuntimeError("无线网卡不是一个，请在配置的 interface 中填写实际网卡名。")
        iface = devices[0]
    if iface not in devices:
        raise RuntimeError("未找到配置指定的无线网卡。")
    return iface


def current_uuid(iface):
    value = nm("-g", "GENERAL.CON-UUID", "device", "show", iface)
    return "" if value == "--" else value


def status(config):
    iface = interface_for(config)
    active = current_uuid(iface)
    ssid = nm("--escape", "no", "-g", "802-11-wireless.ssid", "connection", "show", "uuid", active) if active else ""
    ipv4 = nm("-g", "IP4.ADDRESS", "device", "show", iface).splitlines()
    return dict(interface=iface, ssid=ssid, ipv4=ipv4,
                matches_target=bool(ssid) and ssid == config["ssid"] and bool(ipv4))


def schedule(config):
    if os.geteuid() != 0:
        raise RuntimeError("换网操作需要 sudo 权限。")
    if not shutil.which("systemd-run"):
        raise RuntimeError("小车缺少 systemd-run，无法安排后台换网。")
    iface = interface_for(config)
    previous = current_uuid(iface)
    token = uuid.uuid4().hex
    target = ""
    profile = "smart-car-local-" + token
    unit = "smart-car-wifi-switch-" + token
    # A fresh profile leaves the original password/settings intact for rollback.
    args = ["connection", "add", "type", "wifi", "ifname", iface,
            "con-name", profile, "ssid", config["ssid"],
            "connection.autoconnect", "no",
            "802-11-wireless.hidden", "yes" if config.get("hidden") else "no",
            "802-11-wireless-security.key-mgmt", "wpa-psk",
            "802-11-wireless-security.psk", config["password"]]
    job_dir = None
    try:
        # NetworkManager 1.36 assigns UUIDs itself; connection.uuid is immutable.
        nm(*args)
        target = nm("-g", "connection.uuid", "connection", "show", "id", profile)
        if not target or target == "--":
            raise RuntimeError("未读取到新 Wi-Fi 配置的 UUID。")
        job_dir = Path(tempfile.mkdtemp(prefix="smart-car-wifi-", dir="/run"))
        helper = job_dir / "worker.py"
        shutil.copyfile(__file__, helper)
        job = job_dir / "job.json"
        job.write_text(json.dumps(dict(interface=iface, target=target, previous=previous)), encoding="utf-8")
        helper.chmod(0o600)
        job.chmod(0o600)
        command = ["systemd-run", "--quiet", "--unit=" + unit, "--on-active=5s",
                   "--timer-property=AccuracySec=1s", "--collect", "--property=Type=oneshot",
                   sys.executable, str(helper), "--activate", str(job)]
        result = subprocess.run(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=20)
        if result.returncode:
            raise RuntimeError("后台换网任务创建失败，未开始切换。")
    except Exception:
        if job_dir is not None:
            shutil.rmtree(str(job_dir))
        try:
            nm("connection", "delete", "uuid" if target else "id", target or profile)
        except RuntimeError:
            pass
        raise
    return dict(status="scheduled", ssid=config["ssid"], interface=iface, unit=unit)


def activate(job, job_path):
    switched = False
    try:
        try:
            nm("--wait", "45", "connection", "up", "uuid", job["target"], "ifname", job["interface"], timeout=60)
            if current_uuid(job["interface"]) != job["target"]:
                raise RuntimeError("激活后的连接与目标不一致。")
            nm("connection", "modify", "uuid", job["target"],
               "connection.autoconnect", "yes", "connection.autoconnect-priority", "20")
            switched = True
            print("目标 Wi-Fi 已连接，自动连接设置已保存。", flush=True)
            return 0
        except (RuntimeError, subprocess.TimeoutExpired):
            print("目标 Wi-Fi 切换失败，尝试恢复原连接。", flush=True)
            if job["previous"]:
                nm("--wait", "30", "connection", "up", "uuid", job["previous"], "ifname", job["interface"], timeout=45)
                print("原连接已恢复。", flush=True)
            else:
                print("没有可恢复的原无线连接，请在小车本地处理。", flush=True)
            return 1
    finally:
        if not switched:
            try:
                nm("connection", "delete", "uuid", job["target"])
            except (RuntimeError, subprocess.TimeoutExpired):
                pass
        # These two files were made by schedule inside a private root-owned /run directory.
        job_path.unlink(missing_ok=True)
        Path(__file__).unlink(missing_ok=True)
        job_path.parent.rmdir()


def main():
    if len(sys.argv) != 3 or sys.argv[1] not in ("--schedule", "--status", "--activate"):
        raise RuntimeError("无效的换网工具参数。")
    if not shutil.which("nmcli"):
        raise RuntimeError("小车缺少 nmcli / NetworkManager。")
    path = Path(sys.argv[2])
    config = json.loads(path.read_text(encoding="utf-8"))
    if sys.argv[1] == "--activate":
        return activate(config, path)
    result = status(config) if sys.argv[1] == "--status" else schedule(config)
    print(json.dumps(result, ensure_ascii=False), flush=True)
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except (OSError, ValueError, RuntimeError, subprocess.TimeoutExpired) as exc:
        print(str(exc) if not isinstance(exc, subprocess.TimeoutExpired) else "操作超时，请检查小车网络状态。", file=sys.stderr)
        sys.exit(1)
