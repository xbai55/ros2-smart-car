import { useEffect, useState } from 'react';
import { businessApi, type SystemHealth } from '../../services/businessApi';
import { Link } from '../../lib/router';

export function SystemHealthCard({visible}: {visible: boolean}) {
  const [health, setHealth] = useState<SystemHealth | null>(null);
  const [error, setError] = useState('');
  useEffect(() => {
    if (!visible) return;
    const controller = new AbortController();
    let timer: ReturnType<typeof setTimeout>;
    async function refresh() {
      try {
        const value = await businessApi.assistantHealth(controller.signal);
        if (!controller.signal.aborted) { setHealth(value); setError(''); }
      } catch {
        if (!controller.signal.aborted) { setHealth(null); setError('系统状态暂不可用，不能确认车辆是否正常'); }
      } finally {
        if (!controller.signal.aborted) timer = setTimeout(refresh, 5000);
      }
    }
    void refresh();
    return () => { controller.abort(); clearTimeout(timer); };
  }, [visible]);
  const issues = health?.issues ?? [];
  return <details className="assistant-card assistant-system-health">
    <summary>系统状态 · {error || (health ? issues.length ? `${issues.length} 项待核对` : '当前未观察到故障' : '正在读取')}</summary>
    <p>车辆或系统自身问题；与烟火、人员倒地等巡检告警分开记录。</p>
    {issues.map(issue => <article key={issue.code}><strong>{issue.message}</strong>
      <p>{issue.impact}。{issue.suggestion}</p></article>)}
    {health?.observed_at && <small>查询时间：{new Date(health.observed_at).toLocaleString('zh-CN')}</small>}
    {(health?.history ?? []).slice(0, 8).map(issue => <details key={issue.id}>
      <summary>{issue.state === 'resolved' ? '已恢复' : issue.state === 'active' ? '已确认存在' : '待核对'} · {issue.message}</summary>
      <p>首次观察：{issue.first_seen}；最后观察：{issue.last_seen}</p><p>{issue.suggestion}</p>
    </details>)}
    <p><Link to="/diagnostics">查看日志证据</Link></p>
    <small>现场图片仅按需发送至已配置的模型服务，不持续上传视频。</small>
  </details>;
}
