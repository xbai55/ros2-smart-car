import { useEffect, useState } from 'react';
import { businessApi, type BusinessIncident } from '../../services/businessApi';
import { useData } from '../../hooks/useData';
import { EmptyState, Panel } from '../ui';

export function SafetyRecognitionStatus() {
  const health = useData(() => businessApi.safetyStatus());
  useEffect(() => { const timer = setInterval(health.refetch, 5000); return () => clearInterval(timer); }, [health.refetch]);
  return <Panel title="巡检识别状态"><p role="status">{health.data?.message || health.error || '正在读取车端识别状态…'}</p>
    {health.data?.ingest && <p>{health.data.ingest.message}</p>}
    {health.data?.models?.map(m => <p key={m.path}>{m.path} · {m.validation === 'not_evaluated' ? '尚未完成场景验证' : m.validation}</p>)}
    {health.data?.capabilities && <p>烟火模型：{health.data.capabilities.smoke_fire ? '已加载' : '未配置'}；倒地模型：{health.data.capabilities.fallen_person ? '已加载' : '未配置'}；通道检查截面：{health.data.configured_corridors || 0}个</p>}
    <small>专项模型未配置、摄像头或定位不可用时，不能据此判断现场没有异常。报警后继续巡航，避障和急停独立生效。</small></Panel>;
}

export function IncidentEvidence({ item }: { item: BusinessIncident }) {
  const key = item.media_keys?.find(k => /\.(jpg|jpeg|png)$/i.test(k));
  const [image, setImage] = useState(''), [error, setError] = useState('');
  const asPoints = (value: unknown): number[][] => Array.isArray(value) ? value.filter((p): p is number[] => Array.isArray(p) && p.length === 2 && p.every(v => typeof v === 'number' && Number.isFinite(v))) : [];
  const laser = asPoints(item.evidence?.laser_points), polygon = asPoints(item.evidence?.polygon);
  const coords = [...laser, ...polygon];
  const minX = Math.min(...coords.map(p => p[0])), maxX = Math.max(...coords.map(p => p[0]));
  const minY = Math.min(...coords.map(p => p[1])), maxY = Math.max(...coords.map(p => p[1]));
  useEffect(() => {
    let active = true, url = '';
    setImage(''); setError('');
    if (key) void businessApi.incidentImage(key).then(blob => {
      if (active) { url = URL.createObjectURL(blob); setImage(url); }
    }).catch(e => { if (active) setError((e as Error).message); });
    return () => { active = false; if (url) URL.revokeObjectURL(url); };
  }, [key]);
  return <Panel title="现场证据">{image ? <img src={image} alt="异常发生时保存的现场画面" style={{maxWidth: '100%', maxHeight: 600, objectFit: 'contain'}}/> : <EmptyState title={error ? '现场图片读取失败' : key ? '正在读取现场图片…' : '此记录未保存现场图片'} hint={error || '历史证据与实时摄像头画面分别保存。'}/>}
    {item.type === 'blocked_passage' && <p>图片为同期摄像头视角，相机与雷达视野对应关系尚未现场验证。通道判断以保存的雷达点和检查区域为依据。</p>}
    {coords.length > 1 && <svg role="img" aria-label="报警时的雷达点与通道检查区域" viewBox={`${minX-.2} ${-maxY-.2} ${Math.max(.5,maxX-minX+.4)} ${Math.max(.5,maxY-minY+.4)}`} style={{width:'100%',height:240,background:'#f4f6f9'}}>
      <polygon points={polygon.map(([x,y]) => `${x},${-y}`).join(' ')} fill="#2563eb22" stroke="#2563eb" strokeWidth={.025}/>
      {laser.map(([x,y],i) => <circle key={i} cx={x} cy={-y} r={.025} fill="#d84a44"/>)}
    </svg>}
    {item.evidence?.validation === 'not_evaluated' && <p>此模型尚未完成现场验证，请人工核实。</p>}</Panel>;
}
