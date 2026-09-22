import { ArrowLeft, Layers, Map as MapIcon, Route as RouteIcon } from "lucide-react";
import { Link } from "../lib/router";
import { useData } from "../hooks/useData";
import { adapters } from "../services/adapters";
import { RobotMapCanvas } from "../components/robot/RobotMapCanvas";
import { Badge, EmptyState, Panel } from "../components/ui";
import { DataTable, ObjectHeader, type Column } from "../components/shared";
import type { MapObject, RouteInfo, Robot, Incident } from "../types/domain";

const demoRobots: Robot[] = [];
const demoIncidents: Incident[] = [];

export function MapsPage() {
  const mapsQuery = useData(() => adapters.listMaps());
  const routesQuery = useData(() => adapters.listRoutes());

  const mapColumns: Column<MapObject>[] = [
    { key: "name", header: "地图", render: (m) => <div className="cell-strong"><strong>{m.name}</strong><em>{m.id}</em></div> },
    { key: "area", header: "面积", render: (m) => m.area },
    { key: "version", header: "版本", render: (m) => `v${m.version}` },
    { key: "updated", header: "更新时间", render: (m) => m.updatedAt },
    { key: "status", header: "状态", render: (m) => <Badge tone={m.status === "active" ? "success" : "neutral"}>{m.status === "active" ? "使用中" : "草稿"}</Badge> },
  ];

  const routeColumns: Column<RouteInfo>[] = [
    { key: "name", header: "路线", render: (r) => <div className="cell-strong"><strong>{r.name}</strong><em>{r.id}</em></div> },
    { key: "map", header: "所属地图", render: (r) => r.mapName },
    { key: "distance", header: "距离", render: (r) => `${r.distance} m` },
    { key: "waypoints", header: "航点", render: (r) => `${r.waypoints} 个` },
    { key: "updated", header: "更新时间", render: (r) => r.updatedAt },
  ];

  return (
    <div className="page">
      <ObjectHeader kicker="Maps" title="地图与路线" subtitle="OccupancyGrid 地图、巡检路线与航点管理" badges={[{ label: `${(mapsQuery.data ?? []).length} 张地图`, tone: "blue" }]} />
      <Panel title="地图列表" kicker="Maps" className="list-panel" bodyClassName="panel-flush">
        <DataTable columns={mapColumns} rows={mapsQuery.data ?? []} rowKey={(m) => m.id} loading={mapsQuery.loading} emptyTitle="暂无地图" onRowClick={(m) => { window.location.hash = `/maps/${m.id}`; }} />
      </Panel>
      <Panel title="路线列表" kicker="Routes" className="list-panel" bodyClassName="panel-flush">
        <DataTable columns={routeColumns} rows={routesQuery.data ?? []} rowKey={(r) => r.id} loading={routesQuery.loading} emptyTitle="暂无路线" onRowClick={(r) => { window.location.hash = `/routes/${r.id}`; }} />
      </Panel>
    </div>
  );
}

export function MapDetailPage({ id }: { id: string }) {
  const { data: map } = useData(() => adapters.getMap(id), [id]);
  const routesQuery = useData(() => adapters.listRoutes());
  if (!map) return <div className="page"><EmptyState title="未找到该地图" /></div>;
  const routes = (routesQuery.data ?? []).filter((r) => r.mapId === map.id);

  return (
    <div className="page">
      <Link to="/maps" className="back-link"><ArrowLeft size={15} />地图中心</Link>
      <ObjectHeader kicker={`Map · ${map.id}`} title={map.name} subtitle={`${map.area} · v${map.version} · 更新于 ${map.updatedAt}`} badges={[{ label: map.status === "active" ? "使用中" : "草稿", tone: map.status === "active" ? "success" : "neutral" }]} />
      <div className="map-detail-layout">
        <Panel className="map-detail-canvas" bodyClassName="panel-flush" action={<span className="panel-live"><Layers size={14} />图层控制</span>}>
          <RobotMapCanvas robots={demoRobots} incidents={demoIncidents} />
        </Panel>
        <div className="map-detail-side">
          <Panel title="地图属性" kicker="Properties">
            <div className="profile-list">
              <div><em>名称</em><strong>{map.name}</strong></div>
              <div><em>面积</em><strong>{map.area}</strong></div>
              <div><em>版本</em><strong>v{map.version}</strong></div>
              <div><em>更新时间</em><strong>{map.updatedAt}</strong></div>
            </div>
          </Panel>
          <Panel title="关联路线" kicker="Routes">
            {routes.length ? routes.map((r) => (
              <Link key={r.id} to={`/routes/${r.id}`} className="mini-row"><RouteIcon size={15} /><span><strong>{r.name}</strong><em>{r.waypoints} 航点 · {r.distance} m</em></span></Link>
            )) : <EmptyState title="暂无关联路线" />}
          </Panel>
        </div>
      </div>
    </div>
  );
}

export function RoutesPage() {
  const { data, loading } = useData(() => adapters.listRoutes());
  const columns: Column<RouteInfo>[] = [
    { key: "name", header: "路线", render: (r) => <div className="cell-strong"><strong>{r.name}</strong><em>{r.id}</em></div> },
    { key: "map", header: "所属地图", render: (r) => r.mapName },
    { key: "distance", header: "距离", render: (r) => `${r.distance} m` },
    { key: "waypoints", header: "航点", render: (r) => `${r.waypoints} 个` },
    { key: "version", header: "版本", render: (r) => `v${r.version}` },
    { key: "updated", header: "更新时间", render: (r) => r.updatedAt },
  ];
  return (
    <div className="page">
      <ObjectHeader kicker="Routes" title="路线管理" subtitle="巡检与运输路线的版本、执行记录与航点" />
      <Panel className="list-panel" bodyClassName="panel-flush">
        <DataTable columns={columns} rows={data ?? []} rowKey={(r) => r.id} loading={loading} emptyTitle="暂无路线" onRowClick={(r) => { window.location.hash = `/routes/${r.id}`; }} />
      </Panel>
    </div>
  );
}

export function RouteDetailPage({ id }: { id: string }) {
  const { data: route } = useData(() => adapters.getRoute(id), [id]);
  if (!route) return <div className="page"><EmptyState title="未找到该路线" /></div>;
  const waypoints = Array.from({ length: route.waypoints }).map((_, i) => `WP-${i + 1}`);
  return (
    <div className="page">
      <Link to="/maps" className="back-link"><ArrowLeft size={15} />地图中心</Link>
      <ObjectHeader kicker={`Route · ${route.id}`} title={route.name} subtitle={`${route.mapName} · v${route.version} · 更新于 ${route.updatedAt}`} badges={[{ label: `${route.distance} m`, tone: "blue" }, { label: `${route.waypoints} 航点`, tone: "neutral" }]} />
      <div className="map-detail-layout">
        <Panel className="map-detail-canvas" bodyClassName="panel-flush">
          <RobotMapCanvas robots={demoRobots} incidents={demoIncidents} />
        </Panel>
        <div className="map-detail-side">
          <Panel title="路线属性" kicker="Properties">
            <div className="profile-list">
              <div><em>名称</em><strong>{route.name}</strong></div>
              <div><em>所属地图</em><strong>{route.mapName}</strong></div>
              <div><em>距离</em><strong>{route.distance} m</strong></div>
              <div><em>航点数</em><strong>{route.waypoints}</strong></div>
              <div><em>版本</em><strong>v{route.version}</strong></div>
            </div>
          </Panel>
          <Panel title="航点序列" kicker="Waypoints">
            <ol className="waypoint-list">
              {waypoints.map((wp, i) => <li key={wp}><span>{i + 1}</span>{wp}</li>)}
            </ol>
          </Panel>
        </div>
      </div>
    </div>
  );
}
