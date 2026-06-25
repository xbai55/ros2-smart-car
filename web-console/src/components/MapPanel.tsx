import { useEffect, useMemo, useState } from "react";
import { Grid3X3, Map, Ruler, TimerReset } from "lucide-react";
import { createRobotApi, type MapHealth, type MapSnapshot } from "../robotApi";
import { HudPanel } from "./HudPanel";

type MapPanelProps = { map: MapHealth; active: boolean };

function cellColor(value: number) {
  if (value < 0) return "rgba(104, 137, 160, 0.18)";
  if (value >= 65) return "rgba(255, 110, 105, 0.92)";
  if (value >= 25) return "rgba(255, 211, 105, 0.72)";
  return "rgba(54, 225, 188, 0.2)";
}

export function MapPanel({ map, active }: MapPanelProps) {
  const api = useMemo(() => createRobotApi(), []);
  const [snapshot, setSnapshot] = useState<MapSnapshot | null>(null);
  const [error, setError] = useState("");

  useEffect(() => {
    let cancelled = false;
    let timer: number | undefined;

    const load = async () => {
      if (!active && !map.ok) return;
      try {
        const next = await api.getMap();
        if (!cancelled) {
          setSnapshot(next);
          setError("");
        }
      } catch (reason) {
        if (!cancelled) setError(reason instanceof Error ? reason.message : "map unavailable");
      }
      if (!cancelled) timer = window.setTimeout(load, 1500);
    };

    void load();
    return () => {
      cancelled = true;
      if (timer) window.clearTimeout(timer);
    };
  }, [active, api, map.ok]);

  const width = snapshot?.info.width ?? map.width;
  const height = snapshot?.info.height ?? map.height;
  const resolution = snapshot?.info.resolution ?? map.resolution;
  const cells = snapshot?.data ?? [];
  const viewBox = `0 0 ${Math.max(width, 1)} ${Math.max(height, 1)}`;
  const updatedAge = snapshot ? Math.max(0, Date.now() / 1000 - snapshot.updated_at) : null;

  return (
    <HudPanel
      className="map-panel"
      title="SLAM Map"
      subtitle="二维占据栅格 /map"
      action={<strong className={map.ok ? "map-ok" : "map-warn"}>{map.ok ? "MAP OK" : map.message}</strong>}
    >
      <div className="map-tags">
        <span><Map size={13} /> {map.frame_id || snapshot?.header.frame_id || "--"}</span>
        <span><Grid3X3 size={13} /> {width} x {height}</span>
        <span><Ruler size={13} /> {resolution ? `${resolution.toFixed(2)} m` : "--"}</span>
        <span><TimerReset size={13} /> {updatedAge == null ? "--" : `${updatedAge.toFixed(1)} s`}</span>
      </div>
      <div className="map-canvas" role="img" aria-label="SLAM 二维占据栅格地图">
        {snapshot ? (
          <svg viewBox={viewBox} preserveAspectRatio="xMidYMid meet">
            <rect width={width} height={height} fill="rgba(5, 17, 34, 0.9)" />
            <g transform={`translate(0 ${height}) scale(1 -1)`}>
              {cells.map((value, index) => {
                const x = index % width;
                const y = Math.floor(index / width);
                return <rect key={index} x={x} y={y} width="1" height="1" fill={cellColor(value)} />;
              })}
            </g>
          </svg>
        ) : (
          <div className="map-empty">
            <strong>等待 /map</strong>
            <span>{error || "启动 SLAM 后会显示 OccupancyGrid"}</span>
          </div>
        )}
      </div>
    </HudPanel>
  );
}
