#!/usr/bin/env bash
# Run on the Jetson: sudo bash switch_wifi.sh [SSID] [wifi-interface]
set -euo pipefail
export LC_ALL=C

die() { printf '%s\n' "$*" >&2; exit 1; }
[[ $EUID -eq 0 ]] || die '请使用 sudo bash switch_wifi.sh 运行。'
[[ $# -le 2 ]] || die '用法：sudo bash switch_wifi.sh [Wi-Fi名称] [无线网卡]'
command -v nmcli >/dev/null || die '未安装 nmcli / NetworkManager。'
command -v systemd-run >/dev/null || die '未安装 systemd-run。'

ssid=${1:-}
if [[ -z "$ssid" ]]; then
    read -r -p '目标 Wi-Fi 名称（SSID）：' ssid
fi
[[ -n "$ssid" ]] || die 'Wi-Fi 名称不能为空。'

iface=${2:-}
mapfile -t wifi_devices < <(nmcli -t -f DEVICE,TYPE device status | awk -F: '$2 == "wifi" {print $1}')
if [[ -z "$iface" ]]; then
    [[ ${#wifi_devices[@]} -eq 1 ]] || die '无线网卡不是一个，请用第二个参数指定（例如 wlP1p1s0）。'
    iface=${wifi_devices[0]}
fi
valid_iface=false
for device in "${wifi_devices[@]}"; do
    [[ "$device" != "$iface" ]] || valid_iface=true
done
$valid_iface || die "未找到无线网卡：$iface"

previous_uuid=$(nmcli -g GENERAL.CON-UUID device show "$iface")
[[ "$previous_uuid" != '--' ]] || previous_uuid=''
target_uuid=''
# Match the actual SSID, since a saved connection's name may differ from its SSID.
while IFS=: read -r uuid kind; do
    [[ "$kind" == '802-11-wireless' || "$kind" == 'wifi' ]] || continue
    saved_ssid=$(nmcli --escape no -g 802-11-wireless.ssid connection show uuid "$uuid")
    if [[ "$saved_ssid" == "$ssid" ]]; then
        target_uuid=$uuid
        break
    fi
done < <(nmcli -t -f UUID,TYPE connection show)

if [[ -z "$target_uuid" ]]; then
    printf '%s\n' '没有找到已保存配置。新建配置支持 WPA/WPA2 个人密码网络。'
    read -r -s -p 'Wi-Fi 密码（输入不显示）：' wifi_password
    printf '\n'
    trap 'unset wifi_password' EXIT
    [[ -n "$wifi_password" ]] || die '密码不能为空；开放网络或校园认证网络请先单独配置。'
    profile="smart-car-wifi-$(date +%s)-$$"
    # Save credentials before scheduling the switch; the background job only receives UUIDs.
    nmcli connection add type wifi ifname "$iface" con-name "$profile" ssid "$ssid" \
        802-11-wireless-security.key-mgmt wpa-psk \
        802-11-wireless-security.psk "$wifi_password" \
        connection.autoconnect no
    unset wifi_password
    target_uuid=$(nmcli -g connection.uuid connection show id "$profile")
fi

if [[ "$target_uuid" == "$previous_uuid" ]]; then
    nmcli connection modify uuid "$target_uuid" connection.autoconnect yes connection.autoconnect-priority 20
    printf '已经连接 %s；已保存自动连接设置。\n' "$ssid"
    exit 0
fi

unit="smart-car-wifi-switch-$(date +%s)-$$"
nmcli_bin=$(command -v nmcli)
# A system timer survives SSH disconnection. Restore the previous profile on failure.
# Only make the new network preferred after a successful activation.
systemd-run --unit="$unit" --on-active=5s --timer-property=AccuracySec=1s \
    --collect --property=Type=oneshot /bin/bash -c '
        if "$1" --wait 45 connection up uuid "$2" ifname "$3"; then
            "$1" connection modify uuid "$2" connection.autoconnect yes connection.autoconnect-priority 20
            exit 0
        fi
        printf "%s\n" "目标 Wi-Fi 连接失败，尝试恢复原连接。" >&2
        if [[ -n "$4" && "$4" != "$2" ]]; then
            "$1" --wait 30 connection up uuid "$4" ifname "$3"
        fi
        exit 1
    ' bash "$nmcli_bin" "$target_uuid" "$iface" "$previous_uuid"

printf '已安排约 5 秒后切换至 %s（网卡 %s）。\n' "$ssid" "$iface"
printf '%s\n' 'SSH 可能断开。让电脑接入目标网络，从路由器/热点查看小车的新 IP 后重新连接。'
printf '重新连接后查看结果：sudo journalctl -u %s.service --no-pager -n 40\n' "$unit"
