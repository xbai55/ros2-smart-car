import { Crosshair, Layers, LocateFixed, Minus, Plus, Radio, Route, TriangleAlert } from "lucide-react";
import { useState } from "react";
import { useData } from "../../hooks/useData";
import { adapters, type DemoMap } from "../../services/adapters";
import { uiStore, type MapLayerKey } from "../../stores/uiStore";
import type { Incident, Robot } from "../../types/domain";
import { cn } from "../../lib/cn";

const CELL = 6;
const ROUTE_POINTS: Array<[number, number]> = [
  [10, 76], [32, 76], [32, 66], [40, 66], [40, 40], [52, 40], [52, 62], [68, 62],
  [68, 40], [82, 40], [82, 58], [96, 58], [96, 68], [76, 68], [76, 80], [20, 80], [20, 60], [10, 60],
];
const INCIDENT_POINTS: Array<[number, number]> = [[52, 46], [76, 66], [22, 48], [90, 74], [30, 72]];

function robotToCell(robot: Robot): { x: number; y: number } {
  return { x: (robot.position.x / 100) * 120, y: (1 - robot.position.y / 100) * 90 };
}

const LAYER_LABELS: Array<{ key: MapLayerKey; label: string }> = [
  { key: "occupancy", label: "栅格" },
  { key: "robot", label: "机器人" },
  { key: "lidar", label: "雷达" },
  { key: "route", label: "路线" },
  { key: "incident", label: "异常" },
];

export function RobotMapCanvas({ robots, incidents, className, mapOverride }: { robots: Robot[]; incidents: Incident[]; className?: string; mapOverride?: DemoMap | null }) {
  const layers = uiStore.use().mapLayers;
  const { data: demoMap, loading } = useData<DemoMap>(() => adapters.getDemoMap());
  const map = mapOverride ?? demoMap;
  const mapLoading = loading && !mapOverride;
  const [zoom, setZoom] = useState(1);

  const activeRobots = robots.filter((r) => r.health === "online" || r.health === "degraded" || r.health === "charging");

  return (
    <div className={cn("map-workspace", className)}>
      <div className="map-toolbar">
        <div className="map-toolbar-group layer-toggles">
          <Layers size={14} />
          {LAYER_LABELS.map((layer) => (
            <button
              key={layer.key}
              type="button"
              className={cn("layer-toggle", layers[layer.key] && "on")}
              onClick={() => uiStore.set({ mapLayers: { ...layers, [layer.key]: !layers[layer.key] } })}
            >
              {layer.label}
            </button>
          ))}
        </div>
        <div className="map-toolbar-group zoom-controls">
          <button type="button" aria-label="缩小" onClick={() => setZoom((z) => Math.max(0.7, z - 0.15))}><Minus size={14} /></button>
          <span>{Math.round(zoom * 100)}%</span>
          <button type="button" aria-label="放大" onClick={() => setZoom((z) => Math.min(2, z + 0.15))}><Plus size={14} /></button>
          <button type="button" aria-label="适配视图" onClick={() => setZoom(1)}><LocateFixed size={14} /></button>
        </div>
        <div className="map-toolbar-group map-live"><Radio size={13} />实时</div>
      </div>

      <div className="map-canvas">
        {mapLoading || !map ? (
          <div className="map-loading">正在加载地图…</div>
        ) : (
          <svg viewBox={`0 0 ${map.width} ${map.height}`} className="map-svg" preserveAspectRatio="xMidYMid meet" role="img" aria-label="巡检地图">
            <g transform={`scale(${zoom})`}>
              {layers.occupancy ? <OccupancyLayer map={map} /> : null}
              {layers.route ? <RouteLayer /> : null}
              {layers.incident ? <IncidentLayer incidents={incidents} /> : null}
              {layers.robot ? <RobotLayer robots={activeRobots} /> : null}
              {layers.lidar ? <LidarLayer robots={activeRobots} /> : null}
            </g>
          </svg>
        )}
      </div>

      <div className="map-legend">
        <span><i className="legend-swatch wall" />墙体/障碍</span>
        <span><i className="legend-swatch route" />巡检路线</span>
        <span><i className="legend-swatch robot" />机器人</span>
        <span><i className="legend-swatch incident" />异常点</span>
      </div>
    </div>
  );
}

function OccupancyLayer({ map }: { map: DemoMap }) {
  const rects: React.ReactNode[] = [];
  for (let y = 0; y < map.height; y += 1) {
    for (let x = 0; x < map.width; x += 1) {
      const v = map.data[y * map.width + x];
      if (v >= 65) rects.push(<rect key={`${x}-${y}`} x={x} y={y} width={1.02} height={1.02} className="map-cell" />);
    }
  }
  return (
    <g>
      <rect x={0} y={0} width={map.width} height={map.height} className="map-free" />
      {rects}
    </g>
  );
}

function RouteLayer() {
  const points = ROUTE_POINTS.map(([x, y]) => `${x},${y}`).join(" ");
  return (
    <g>
      <polyline points={points} fill="none" className="map-route-shadow" />
      <polyline points={points} fill="none" className="map-route" strokeDasharray="2 1.4" />
      {ROUTE_POINTS.map(([x, y], i) => <circle key={i} cx={x} cy={y} r={i === 0 || i === ROUTE_POINTS.length - 1 ? 0.9 : 0.5} className="map-route-node" />)}
    </g>
  );
}

function RobotLayer({ robots }: { robots: Robot[] }) {
  return (
    <g>
      {robots.map((robot) => {
        const { x, y } = robotToCell(robot);
        const tone = robot.health === "degraded" ? "degraded" : robot.health === "charging" ? "charging" : "online";
        return (
          <g key={robot.id} transform={`translate(${x},${y})`}>
            <circle r={1.6} className={`robot-halo robot-${tone}`} />
            <g transform={`rotate(${robot.heading})`}>
              <path d="M0,-1.1 L0.9,0.7 L0,0.4 L-0.9,0.7 Z" className={`robot-marker robot-${tone}`} />
            </g>
          </g>
        );
      })}
    </g>
  );
}

function LidarLayer({ robots }: { robots: Robot[] }) {
  return (
    <g>
      {robots.map((robot) => {
        const { x, y } = robotToCell(robot);
        const radius = 6;
        const rad = (robot.heading * Math.PI) / 180;
        const ex = x + Math.cos(rad) * radius;
        const ey = y + Math.sin(rad) * radius;
        return (
          <g key={robot.id}>
            <line x1={x} y1={y} x2={ex} y2={ey} className="lidar-beam" />
            <circle cx={x} cy={y} r={radius} className="lidar-range" />
          </g>
        );
      })}
    </g>
  );
}

function IncidentLayer({ incidents }: { incidents: Incident[] }) {
  const open = incidents.filter((i) => i.status === "open" || i.status === "confirmed");
  return (
    <g>
      {open.map((incident, i) => {
        const [x, y] = INCIDENT_POINTS[i % INCIDENT_POINTS.length];
        return (
          <g key={incident.id} transform={`translate(${x},${y})`} className="incident-marker">
            <circle r={2} className="incident-ring" />
            <TriangleAlert x={-1} y={-1} width={2} height={2} />
          </g>
        );
      })}
    </g>
  );
}
