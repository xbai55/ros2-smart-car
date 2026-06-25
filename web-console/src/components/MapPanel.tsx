import { useEffect, useMemo, useState } from "react";
import {
  Activity,
  AlertTriangle,
  CheckCircle2,
  Grid3X3,
  Layers,
  Map,
  RotateCcw,
  Ruler,
  TimerReset,
} from "lucide-react";
import { createRobotApi, type LidarHealth, type MapHealth, type MapSnapshot } from "../robotApi";
import { HudPanel } from "./HudPanel";

type MapPanelProps = {
  map: MapHealth;
  lidar: LidarHealth;
  active: boolean;
  speed: number;
  restarting?: boolean;
  onRestart?: () => void;
};

type MapViewMode = "enhanced" | "raw";
type QualityTone = "good" | "warn" | "bad";

function rawCellColor(value: number) {
  if (value < 0) return "#071b2f";
  if (value < 25) return "#11344b";
  if (value < 65) return "#23556a";
  return "#19dfff";
}

function occupiedNeighborCount(cells: number[], width: number, height: number, x: number, y: number) {
  let count = 0;
  for (let dy = -1; dy <= 1; dy += 1) {
    for (let dx = -1; dx <= 1; dx += 1) {
      if (dx === 0 && dy === 0) continue;
      const nx = x + dx;
      const ny = y + dy;
      if (nx < 0 || ny < 0 || nx >= width || ny >= height) continue;
      if ((cells[ny * width + nx] ?? -1) >= 65) count += 1;
    }
  }
  return count;
}

function enhancedCellColor(value: number, neighbors: number) {
  if (value < 0) return "#071b2f";
  if (value < 25) return "#11344b";
  if (value < 65) return "#23556a";
  if (neighbors <= 1) return "#35a9d1";
  if (neighbors <= 3) return "#26c7f2";
  return "#19dfff";
}

function calculateNoiseRatio(cells: number[], width: number, height: number) {
  let occupied = 0;
  let isolated = 0;
  cells.forEach((value, index) => {
    if (value < 65) return;
    occupied += 1;
    const x = index % width;
    const y = Math.floor(index / width);
    if (occupiedNeighborCount(cells, width, height, x, y) <= 1) isolated += 1;
  });
  return occupied === 0 ? 0 : isolated / occupied;
}

function qualityLabel(map: MapHealth, lidar: LidarHealth, speed: number, noiseRatio: number | null) {
  if (!map.ok || !lidar.ok) {
    return { tone: "bad" as QualityTone, text: "风险", detail: "SCAN/MAP 状态异常" };
  }
  if (speed > 25) {
    return { tone: "warn" as QualityTone, text: "一般", detail: "建图速度偏高" };
  }
  if (noiseRatio != null && noiseRatio > 0.18) {
    return { tone: "warn" as QualityTone, text: "一般", detail: "孤立障碍点偏多" };
  }
  return { tone: "good" as QualityTone, text: "良好", detail: "低速且数据实时" };
}

function statusClass(ok: boolean) {
  return ok ? "ok" : "bad";
}

export function MapPanel({ map, lidar, active, speed, restarting = false, onRestart }: MapPanelProps) {
  const api = useMemo(() => createRobotApi(), []);
  const [snapshot, setSnapshot] = useState<MapSnapshot | null>(null);
  const [error, setError] = useState("");
  const [viewMode, setViewMode] = useState<MapViewMode>("enhanced");

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

  useEffect(() => {
    if (!map.ok && map.message === "restarting") setSnapshot(null);
  }, [map.message, map.ok]);

  const width = snapshot?.info.width ?? map.width;
  const height = snapshot?.info.height ?? map.height;
  const resolution = snapshot?.info.resolution ?? map.resolution;
  const cells = snapshot?.data ?? [];
  const viewBox = `0 0 ${Math.max(width, 1)} ${Math.max(height, 1)}`;
  const updatedAge = snapshot ? Math.max(0, Date.now() / 1000 - snapshot.updated_at) : null;
  const noiseRatio = snapshot ? calculateNoiseRatio(cells, width, height) : null;
  const quality = qualityLabel(map, lidar, speed, noiseRatio);
  const speedOk = speed <= 25;

  return (
    <HudPanel
      className="map-panel"
      title="SLAM Map"
      subtitle="二维占据栅格 /map"
      action={<strong className={map.ok ? "map-ok" : "map-warn"}>{map.ok ? "MAP OK" : map.message}</strong>}
    >
      <div className="map-control-strip">
        <div className="map-tags">
          <span><Map size={13} /> {map.frame_id || snapshot?.header.frame_id || "--"}</span>
          <span><Grid3X3 size={13} /> {width} x {height}</span>
          <span><Ruler size={13} /> {resolution ? `${resolution.toFixed(2)} m` : "--"}</span>
          <span><TimerReset size={13} /> {updatedAge == null ? "--" : `${updatedAge.toFixed(1)} s`}</span>
        </div>
        <div className="map-actions">
          <button type="button" onClick={onRestart} disabled={!onRestart || restarting}>
            <RotateCcw size={14} />{restarting ? "重启中" : "重启建图"}
          </button>
          <button type="button" onClick={() => setViewMode((mode) => mode === "enhanced" ? "raw" : "enhanced")}>
            <Layers size={14} />{viewMode === "enhanced" ? "切到原始" : "切到美化"}
          </button>
        </div>
      </div>

      <div className="map-health-strip">
        <span className={statusClass(lidar.ok)}>{lidar.ok ? <CheckCircle2 size={13} /> : <AlertTriangle size={13} />} SCAN</span>
        <span className={statusClass(map.ok)}>{map.ok ? <CheckCircle2 size={13} /> : <AlertTriangle size={13} />} MAP</span>
        <span className={statusClass(speedOk)}>{speedOk ? <CheckCircle2 size={13} /> : <AlertTriangle size={13} />} {speed}%</span>
        <span className={quality.tone}><Activity size={13} /> 建图质量 {quality.text}</span>
        <b>{quality.detail}</b>
      </div>

      <div className="map-canvas" role="img" aria-label="SLAM 二维占据栅格地图">
        {snapshot ? (
          <>
            <svg viewBox={viewBox} preserveAspectRatio="xMidYMid meet" className={viewMode === "enhanced" ? "map-enhanced" : "map-raw"}>
              <rect width={width} height={height} fill={viewMode === "enhanced" ? "#020b16" : "rgba(2, 12, 27, 0.98)"} />
              <g transform={`translate(0 ${height}) scale(1 -1)`}>
                {cells.map((value, index) => {
                  const x = index % width;
                  const y = Math.floor(index / width);
                  const neighbors = value >= 65 ? occupiedNeighborCount(cells, width, height, x, y) : 0;
                  const fill = viewMode === "enhanced" ? enhancedCellColor(value, neighbors) : rawCellColor(value);
                  const stroke = viewMode === "enhanced" ? "#08263d" : "none";
                  const strokeWidth = viewMode === "enhanced" ? 0.035 : 0;
                  return (
                    <rect
                      key={index}
                      x={x}
                      y={y}
                      width={1}
                      height={1}
                      fill={fill}
                      stroke={stroke}
                      strokeWidth={strokeWidth}
                    />
                  );
                })}
              </g>
            </svg>
          </>
        ) : (
          <div className="map-empty">
            <strong>{restarting ? "正在重启 SLAM" : "等待 /map"}</strong>
            <span>{error || "启动或重启建图后会显示 OccupancyGrid"}</span>
          </div>
        )}
      </div>

      <div className="map-legend">
        <span><i className="legend-free" />可通行区域</span>
        <span><i className="legend-obstacle" />占据障碍物</span>
        <span><i className="legend-noise" />低置信区域</span>
        <span><i className="legend-unknown" />未识别区域</span>
      </div>
    </HudPanel>
  );
}
