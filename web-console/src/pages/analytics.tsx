import { useData } from "../hooks/useData";
import { businessApi } from "../services/businessApi";
import { EmptyState, Panel } from "../components/ui";
import { ObjectHeader } from "../components/shared";
export function AnalyticsPage() {
  const { data, loading, error, refetch } = useData(() => businessApi.analyticsSummary());
  return <div className="page"><ObjectHeader kicker="Analytics" title="数据洞察" subtitle="按业务数据库记录统计；不代表实车任务执行验收" actions={<button className="btn btn-outline" onClick={refetch}>刷新</button>}/><Panel title="业务记录汇总">{loading ? <EmptyState title="加载中…"/> : error ? <EmptyState title="统计数据不可用" hint={error}/> : data && <div className="profile-list"><div><em>巡检任务记录</em><strong>{data.patrol.total}</strong></div><div><em>运输任务记录</em><strong>{data.mission.total}</strong></div><div><em>异常记录</em><strong>{data.incident.total}</strong></div><div><em>未关闭异常记录</em><strong>{data.incident.unresolved}</strong></div></div>}</Panel><Panel title="实车运行统计"><EmptyState title="运行历史指标未采集" hint="尚未采集实车任务完成历史、利用率和巡检覆盖率，不生成相应趋势图。"/></Panel></div>;
}
