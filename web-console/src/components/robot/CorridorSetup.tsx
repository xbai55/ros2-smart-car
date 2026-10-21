import { useEffect, useState } from 'react';
import { businessApi, createMapRequestId, type SafetyCorridor } from '../../services/businessApi';
import { drawingToWorld, drawingYawToWorld, type Calibration, type Place } from '../../labNavigation';
import { useBusinessSession } from '../../hooks/useBusinessSession';

export function CorridorSetup({target, calibration, mapKey, controlSessionId, locked}: {
  target: Place | null; calibration: Calibration | null; mapKey: string; controlSessionId?: string | null; locked: boolean;
}) {
  const session = useBusinessSession();
  const [zones, setZones] = useState<SafetyCorridor[]>([]), [width, setWidth] = useState(1.2), [freeWidth, setFreeWidth] = useState(.65);
  const [error, setError] = useState(''), [busy, setBusy] = useState(false), [loaded, setLoaded] = useState(false);
  const manage = !!session?.user.role?.permissions.some(p => p.name === 'incidents.manage');
  useEffect(() => {
    let active = true; setLoaded(false);
    if (session) void businessApi.safetyCorridors().then(v => { if (active) {setZones(v.corridors.filter(z => z.map_key === mapKey)); setError(''); setLoaded(true);} }).catch(e => { if (active) setError((e as Error).message); });
    return () => { active = false; };
  }, [mapKey, session?.user.id]);
  async function save(next: SafetyCorridor[]) {
    if (!calibration) return;
    setBusy(true); setError('');
    try { const value = await businessApi.saveSafetyCorridors({corridors: next, map_key: mapKey, control_session_id: controlSessionId,
      calibration_matrix: calibration.matrix, calibration_drawing: calibration.drawing}); setZones(value.corridors.filter(z => z.map_key === mapKey)); }
    catch (e) { setError((e as Error).message); } finally { setBusy(false); }
  }
  function add() {
    if (!target || !calibration) return;
    if (!Number.isFinite(width) || !Number.isFinite(freeWidth) || width < .4 || width > 5 || freeWidth < .2 || freeWidth > 3 || freeWidth >= width) { setError('请核对通道宽度与所需净宽'); return; }
    const center = drawingToWorld(target.drawing, calibration.matrix), yaw = drawingYawToWorld(target.yaw, calibration.matrix);
    const c = Math.cos(yaw), s = Math.sin(yaw);
    const polygon = [[-.15,-width/2],[.15,-width/2],[.15,width/2],[-.15,width/2]].map(([x,y]) => [center.x+c*x-s*y, center.y+s*x+c*y]);
    void save([...zones, {id:createMapRequestId(), name: target.name, map_key:mapKey, polygon, axis_yaw:yaw, required_free_width_m:freeWidth}]);
  }
  const disabled = locked || busy || !manage || !loaded || !calibration;
  return <details className="navigation-setup"><summary>通道堵塞检查区域</summary>
    <p>在地图中选取通道中央，目标朝向沿通道延伸方向；检查范围为前后各0.15米的横截面。持续缺少足够净宽时产生报警。</p>
    <label>实际通道宽度（米）<input type="number" min={.4} max={5} step={.1} value={width} onChange={e => setWidth(Number(e.target.value))}/></label>
    <label>小车所需净宽（米）<input type="number" min={.2} max={3} step={.05} value={freeWidth} onChange={e => setFreeWidth(Number(e.target.value))}/></label>
    <button className="btn btn-outline" disabled={disabled || !target || zones.length >= 30} onClick={add}>将当前目标设为检查截面</button>
    <ul>{zones.map(z => <li key={z.id}>{z.name} · 所需净宽{z.required_free_width_m}米 <button disabled={disabled} onClick={() => void save(zones.filter(v => v.id !== z.id))}>移除</button></li>)}</ul>
    {locked && <p>请先停止小车并结束执行任务，再修改检查区域。</p>}{error && <p role="alert">{error}</p>}
    <small>雷达只能判断扫描平面的占用；不能确认其上下方没有障碍，现场仍需验证。</small>
  </details>;
}
