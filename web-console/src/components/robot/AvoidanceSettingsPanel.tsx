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
  const full = value?.settings.protection_mode === 'full';
  const profileSupported = value?.protection_supported === true;
  const actualEnabled = value?.confirmed && value.settings.enabled;
  const actualMode = value?.confirmed && profileSupported ? full ? '完整防护' : '基础防护' : '等待车端确认';
  return <section className="motion-setting" aria-label="运动防护设置">
    <div className="setting-title"><ShieldCheck size={16}/><strong>运动防护</strong><span>{actualMode}</span></div>
    <button type="button" role="switch" aria-label="完整防护模式" aria-checked={full && !!value?.confirmed}
      disabled={!editable || !profileSupported || !!value?.recovery_required}
      onClick={() => void robot.setAvoidance({protection_mode: full ? 'basic' : 'full'})}>
      {full ? '切换为基础防护' : '开启完整防护模式'}</button>
    <p className="setting-note">基础模式仅按实际测得的障碍距离防撞，正常采样缺口不锁车；急停、松手、断连、指令过期停车和限速保留。雷达整体失联或没有有效测距时仍会停车。完整模式另检查观测覆盖与位姿。</p>
    {!profileSupported && connected && <p className="setting-note">车端尚未确认支持防护模式，请更新车端后再设置。</p>}
    {value?.recovery_required && <button type="button" disabled={!editable || !value.motion_epoch}
      onClick={() => value.motion_epoch && void robot.setAvoidance({acknowledge: value.motion_epoch})}>确认故障恢复（须先停车）</button>}
    {value?.output && <p className="setting-note" role="status">{value.output.allowed ? '最终速度已放行' : `当前未输出运动：${value.output.reasons.map(protectionReason).join('、') || '等待新的驾驶操作'}`}。{value.output.recovery}</p>}
    {value?.config_rejection && <p className="setting-note" role="alert">设置未更改：{value.config_rejection}</p>}
    {value?.scan_fault && <p className="setting-note">雷达链路：{protectionReason(value.scan_fault)}</p>}
    {value?.velocity && <p className="setting-note">底盘速度证据：{value.velocity.ok ? '有效' : '无效或过期'}，年龄 {value.velocity.age_sec?.toFixed(3) ?? '—'} 秒。</p>}
    <div className="setting-title"><ShieldCheck size={16}/><strong>主动绕行</strong><span>{!connected ? '未连接' : !supported ? '车端不支持' : !value?.confirmed ? '等待确认' : actualEnabled ? '已开启' : '已关闭'}</span></div>
    <div className="setting-presets"><button type="button" role="switch" aria-label="主动避障开关" aria-checked={!!actualEnabled} disabled={!editable || !!value?.recovery_required} onClick={() => void robot.setAvoidance({ enabled: !enabled })}>{enabled ? '关闭主动绕行' : '开启主动绕行'}</button></div>
    <label>触发距离（距车体前缘，米）</label>
    <div className="threshold-editor"><input aria-label="主动避障触发距离" type="number" min={.4} max={1.5} step={.05} value={distance} disabled={!editable || !!value?.recovery_required} onChange={e => setDistance(e.target.value)}/><button type="button" className="setting-apply" disabled={!editable || !valid} onClick={() => void robot.setAvoidance({ trigger_distance_m: Number(distance) })}>应用距离</button></div>
    <p className="live-helper" role="status">{!connected ? '等待小车连接' : !supported ? '请更新车端以使用主动避障' : `${labels[value!.state] ?? value!.state}${value?.direction ? value.direction === 'left' ? ' · 左侧' : ' · 右侧' : ''} · ${value!.reason}`}</p>
    {connected && supported && value?.confirmed && !value.available && !value.recovery_required && <p className="setting-note">传感器尚未就绪，运动将被拦截。</p>}
    {connected && supported && value?.last_stop_event && <p className="setting-note">最近安全拦截：{value.last_stop_event.reason}</p>}
    {connected && supported && value?.blocking_point_m && <p className="setting-note">{value.coverage?.kind==='unknown'?'未观测区域检查位置（不是障碍物测距）':'阻挡检查位置'}：前向 {value.blocking_point_m[0].toFixed(2)} m，左向 {value.blocking_point_m[1].toFixed(2)} m；负值表示反方向。</p>}
    {connected && value?.missing_data_policy?.mode==='assume_clear' && <p className="setting-note">无回波按空旷处理：{value.missing_data_policy.active ? `已生效，本帧 ${value.assumed_clear?.rays??0} 个缺测方向按空旷处理` : '等待扫描条件满足'}。这是操作者指定的假设，不代表雷达已确认空旷；真实障碍和设备故障仍会停车。</p>}
    {connected && !value?.missing_data_policy?.active && value?.sampling_gap_inferred && <p className="setting-note">小采样间隙推断：{value.sampling_gap_inferred.rays} 条射线，距离上限 {value.sampling_gap_inferred.distance_cap_min_m.toFixed(2)}～{value.sampling_gap_inferred.distance_cap_max_m.toFixed(2)} m，超过上限仍未知。</p>}
    {connected && value?.scan_health && <p className="setting-note">有效点 {((value.scan_health.valid_ratio??0)*100).toFixed(0)}%，扫描 {value.scan_health.scan_rate_hz?.toFixed(1)??'—'} Hz，连续健康 {value.scan_health.consecutive_healthy??0} 帧。</p>}
    <p className="setting-note">基础防撞缓冲 5 cm；制动距离、数据延迟及更大的模式距离设置仍会增加保护范围。导航由 Nav2 绕行；关闭主动绕行仍保留防撞停车。本地绕行规划需要有效里程计位姿；基础直行不依赖全局位姿。</p>
    <p className="setting-note">通道足够时约为原速度的 80%，最高 0.25 m/s；转向与近障时减速。</p>
  </section>;
}
