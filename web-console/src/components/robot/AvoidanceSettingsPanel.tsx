import { useEffect, useState } from 'react';
import { ShieldCheck } from 'lucide-react';
import { protectionReason } from '../../protectionStatus';
import { useRobotStream } from '../../hooks/useRobotStream';

const labels: Record<string, string> = { idle: '待命', waiting: '等待控制器确认', waiting_observation: '缺少可靠观测，条件恢复后松开再按', assessing: '制动评估', turning: '转向绕行', passing: '绕过障碍', recovering: '恢复方向', braking: '减速制动', blocked: '道路堵塞', sensor_fault: '传感器异常', timeout: '绕行已停止', nav2: 'Nav2 规划绕行', recovery_required: '等待人工确认恢复' };
export function AvoidanceSettingsPanel({ connected }: { connected: boolean }) {
  const robot = useRobotStream(), value = robot.status.avoidance;
  const settings = value?.requested ?? value?.settings;
  const [distance, setDistance] = useState(String(settings?.trigger_distance_m ?? .6));
  useEffect(() => setDistance(String(settings?.trigger_distance_m ?? .6)), [settings?.trigger_distance_m]);
  const supported = value?.supported === true;
  const editable = connected && supported && robot.status.mode === 'stop' && !robot.pending;
  const valid = distance.trim() !== '' && Number.isFinite(Number(distance)) && Number(distance) >= .4 && Number(distance) <= 1.5;
  const enabled = settings?.enabled === true;
  const actualEnabled = value?.confirmed && value.settings.enabled;
  const applied = robot.status.navigation.dynamic_avoidance;
  return <section className="motion-setting" aria-label="主动避障设置">
    <div className="setting-title"><ShieldCheck size={16}/><strong>运动防护</strong><span>雷达防撞与停车保护</span></div>
    {value?.recovery_required && <button type="button" disabled={!editable || !value.motion_epoch}
      onClick={() => value.motion_epoch && void robot.setAvoidance({acknowledge: value.motion_epoch})}>确认故障恢复（须先停车）</button>}
    {value?.output && <p className="setting-note" role="status">{value.output.allowed ? '最终速度已放行' : `当前未输出运动：${value.output.reasons.map(protectionReason).join('、') || '等待新的驾驶操作'}`}。{value.output.recovery}</p>}
    {value?.config_rejection && <p className="setting-note" role="alert">设置未更改：{value.config_rejection}</p>}
    {value?.scan_fault && <p className="setting-note">雷达链路：{protectionReason(value.scan_fault)}</p>}
    {value?.velocity && <p className="setting-note">底盘速度证据：{value.velocity.ok ? '有效' : '无效或过期'}，年龄 {value.velocity.age_sec?.toFixed(3) ?? '—'} 秒。</p>}
    <div className="setting-title"><ShieldCheck size={16}/><strong>主动避障</strong><span>{!connected ? '未连接' : !supported ? '车端不支持' : !value?.confirmed ? '等待确认' : actualEnabled ? '已开启' : '已关闭'}</span></div>
    <div className="setting-presets"><button type="button" role="switch" aria-label="主动避障开关" aria-checked={!!actualEnabled} disabled={!editable || !!value?.recovery_required} onClick={() => void robot.setAvoidance({ enabled: !enabled, protection_mode: "basic" })}>{enabled ? '关闭主动避障' : '开启主动避障'}</button></div>
    <p className="setting-note">开关在下一次路线预览时应用到 Nav2。关闭：静态地图规划，遇动态近障停车；开启：雷达障碍层参与规划并绕行，障碍消失后继续。急停、失联、限速和近障停车始终保留。</p>
    <p className="setting-note" role="status">Nav2 实际状态：{applied?.enabled == null ? '等待路线预览确认' : applied.enabled ? '动态避障已开启' : '动态避障已关闭'}。{applied?.message}</p>
    <label>本地绕行触发距离（距车体前缘，米）</label>
    <div className="threshold-editor"><input aria-label="主动避障触发距离" type="number" min={.4} max={1.5} step={.05} value={distance} disabled={!editable || !!value?.recovery_required} onChange={e => setDistance(e.target.value)}/><button type="button" className="setting-apply" disabled={!editable || !valid} onClick={() => void robot.setAvoidance({ trigger_distance_m: Number(distance) })}>应用距离</button></div>
    <p className="live-helper" role="status">{!connected ? '等待小车连接' : !supported ? '请更新车端以使用主动避障' : `${labels[value!.state] ?? value!.state}${value?.direction ? value.direction === 'left' ? ' · 左侧' : ' · 右侧' : ''} · ${value!.reason}`}</p>
    {connected && supported && value?.confirmed && !value.available && !value.recovery_required && <p className="setting-note">传感器尚未就绪，运动将被拦截。</p>}
    {connected && supported && value?.last_stop_event && <p className="setting-note">最近安全拦截：{value.last_stop_event.reason}</p>}
    {connected && supported && value?.blocking_point_m && <p className="setting-note">{value.coverage?.kind==='unknown'?'未观测区域检查位置（不是障碍物测距）':'阻挡检查位置'}：前向 {value.blocking_point_m[0].toFixed(2)} m，左向 {value.blocking_point_m[1].toFixed(2)} m；负值表示反方向。</p>}
    {connected && value?.missing_data_policy?.mode==='assume_clear' && <p className="setting-note">无回波按空旷处理：{value.missing_data_policy.active ? `已生效，本帧 ${value.assumed_clear?.rays??0} 个缺测方向按空旷处理` : '等待扫描条件满足'}。这是操作者指定的假设，不代表雷达已确认空旷；真实障碍和设备故障仍会停车。</p>}
    {connected && !value?.missing_data_policy?.active && value?.sampling_gap_inferred && <p className="setting-note">小采样间隙推断：{value.sampling_gap_inferred.rays} 条射线，距离上限 {value.sampling_gap_inferred.distance_cap_min_m.toFixed(2)}～{value.sampling_gap_inferred.distance_cap_max_m.toFixed(2)} m，超过上限仍未知。</p>}
    {connected && value?.scan_health && <p className="setting-note">有效点 {((value.scan_health.valid_ratio??0)*100).toFixed(0)}%，扫描 {value.scan_health.scan_rate_hz?.toFixed(1)??'—'} Hz，连续健康 {value.scan_health.consecutive_healthy??0} 帧。</p>}
    <p className="setting-note">车体尺寸与 5 cm 基础净空保持不变，制动距离和观测延迟参与近障检查。导航绕行由 Nav2 执行，本地绕行距离设置用于非导航驾驶。</p>
  </section>;
}
