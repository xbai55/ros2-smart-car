import { Link } from "../lib/router";
import { useData } from "../hooks/useData";
import { businessApi, type ManagedRoute } from "../services/businessApi";
import { formatTime } from "../services/adapters";
import { EmptyState, Panel } from "../components/ui";
import { DataTable, ObjectHeader, type Column } from "../components/shared";
import { ManagedMapsPage, ManagedMapDetailPage } from "../components/maps/MapManager";
export const MapsPage = ManagedMapsPage;
export const MapDetailPage = ManagedMapDetailPage;
export function RoutesPage() {
  const { data, loading, error } = useData(() => businessApi.listRoutes());
  const columns: Column<ManagedRoute>[] = [
    { key: "name", header: "路线", render: r => r.name },
    { key: "map", header: "地图 ID", render: r => r.map_id || "未关联" },
    { key: "points", header: "已保存航点", render: r => r.waypoints.length },
    { key: "time", header: "更新时间", render: r => formatTime(r.updated_at || r.created_at) },
  ];
  return <div className="page"><ObjectHeader kicker="Routes" title="路线管理" subtitle="业务服务已保存的路线；实际导航路线请在实操页预览"/><Panel className="list-panel" bodyClassName="panel-flush">{error ? <EmptyState title="路线数据不可用" hint={error}/> : <DataTable columns={columns} rows={data || []} rowKey={r => r.id} loading={loading} emptyTitle="暂无路线记录" onRowClick={r => { window.location.hash = `/routes/${r.id}`; }}/>}</Panel></div>;
}
export function RouteDetailPage({ id }: { id: string }) {
  const { data: route, loading, error } = useData(() => businessApi.getRoute(id), [id]);
  return <div className="page"><Link to="/routes" className="back-link">返回路线管理</Link>{loading ? <EmptyState title="加载中…"/> : error ? <EmptyState title="路线数据不可用" hint={error}/> : !route ? <EmptyState title="未找到该路线"/> : <><ObjectHeader kicker="Route" title={route.name} subtitle="已保存的业务路线，不代表已在实车执行"/><Panel title="航点记录">{route.waypoints.length ? <ol>{route.waypoints.map((p, i) => <li key={i}><code>{JSON.stringify(p)}</code></li>)}</ol> : <EmptyState title="未保存航点"/>}</Panel>{route.map_id && <Link to={`/maps/${route.map_id}`} className="btn btn-outline">查看关联地图</Link>}</>}</div>;
}
