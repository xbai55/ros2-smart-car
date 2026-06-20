import { Database, RadioTower, ScanLine, Sigma } from "lucide-react";
import type { RadarPoint } from "../robotApi";
import { HudPanel } from "./HudPanel";

const center = { x: 420, y: 330 };
const maxRadius = 300;
const maxDistance = 3;
const rings = [0.5, 1, 1.5, 2, 2.5, 3];
const angles = [-90, -60, -30, 0, 30, 60, 90];

function polarPoint(angle: number, distance: number) {
  const normalized = (90 - angle) * (Math.PI / 180);
  const radius = (distance / maxDistance) * maxRadius;
  return {
    x: center.x + Math.cos(normalized) * radius,
    y: center.y - Math.sin(normalized) * radius
  };
}

function arcPath(radius: number) {
  return `M ${center.x - radius} ${center.y} A ${radius} ${radius} 0 0 1 ${center.x + radius} ${center.y}`;
}

type LidarPanelProps = { points: RadarPoint[]; frontDistance: number | null };

export function LidarPanel({ points, frontDistance }: LidarPanelProps) {
  const lidarPoints = points.map((point) => {
    let angle = Math.atan2(point.y, point.x) * 180 / Math.PI;
    if (angle > 90) angle -= 180;
    if (angle < -90) angle += 180;
    return { angle, distance: Math.min(point.distance, maxDistance), strength: 0.82 };
  });
  const nearest = frontDistance ?? (points.length ? Math.min(...points.map((point) => point.distance)) : null);
  return (
    <HudPanel
      className="lidar-panel"
      title="Lidar Scan"
      subtitle="雷达数据可视化"
      action={<strong className="point-count">{points.length} 点</strong>}
    >
      <div className="lidar-tags">
        <span>
          <Sigma size={13} /> 点数 {points.length}
        </span>
        <span>
          <RadioTower size={13} /> Nearest {nearest == null ? "--" : `${nearest.toFixed(2)}m`}
        </span>
        <span>
          <ScanLine size={13} /> Front 180°
        </span>
        <span>
          <Database size={13} /> /scan
        </span>
        <span>实时 WebSocket</span>
      </div>
      <svg className="lidar-svg" viewBox="0 0 840 360" role="img" aria-label="半圆激光雷达扫描图">
        <defs>
          <pattern id="tinyGrid" width="24" height="24" patternUnits="userSpaceOnUse">
            <path d="M 24 0 L 0 0 0 24" fill="none" stroke="#0b88d8" strokeWidth="0.45" opacity="0.55" />
          </pattern>
          <radialGradient id="scanGlow" cx="50%" cy="100%" r="80%">
            <stop offset="0%" stopColor="#5cf7d4" stopOpacity="0.86" />
            <stop offset="45%" stopColor="#10d8ff" stopOpacity="0.28" />
            <stop offset="100%" stopColor="#0a87ff" stopOpacity="0" />
          </radialGradient>
          <linearGradient id="arcGradient" x1="0%" y1="100%" x2="100%" y2="10%">
            <stop offset="0%" stopColor="#00b7ff" stopOpacity="0.92" />
            <stop offset="50%" stopColor="#39f4ff" stopOpacity="0.78" />
            <stop offset="100%" stopColor="#0091ff" stopOpacity="0.92" />
          </linearGradient>
          <filter id="pointGlow" x="-80%" y="-80%" width="260%" height="260%">
            <feGaussianBlur stdDeviation="3" result="blur" />
            <feMerge>
              <feMergeNode in="blur" />
              <feMergeNode in="SourceGraphic" />
            </feMerge>
          </filter>
        </defs>

        <rect width="840" height="360" fill="url(#tinyGrid)" opacity="0.4" />
        <g className="lidar-grid">
          {rings.map((ring) => (
            <path key={ring} d={arcPath((ring / maxDistance) * maxRadius)} />
          ))}
          {angles.map((angle) => {
            const end = polarPoint(angle, maxDistance);
            const label = polarPoint(angle, 3.15);
            return (
              <g key={angle}>
                <line x1={center.x} y1={center.y} x2={end.x} y2={end.y} />
                <text x={label.x} y={label.y + (angle === 0 ? -2 : 5)} textAnchor="middle">
                  {angle}°
                </text>
              </g>
            );
          })}
          <line x1={center.x - maxRadius} y1={center.y} x2={center.x + maxRadius} y2={center.y} />
        </g>

        <g className="distance-labels">
          {rings.map((ring) => {
            const p = polarPoint(88, ring);
            return (
              <text key={ring} x={p.x + 24} y={p.y + 4}>
                {ring.toFixed(1)}m
              </text>
            );
          })}
          {[0.5, 1, 1.5, 2, 2.5, 3].map((ring) => {
            const p = polarPoint(-2, ring);
            return (
              <text key={`base-${ring}`} x={p.x - 14} y={center.y + 24} textAnchor="middle">
                {ring.toFixed(1)}m
              </text>
            );
          })}
        </g>

        <g className="scan-beam">
          <path d={`M ${center.x} ${center.y} L ${polarPoint(-22, 2.6).x} ${polarPoint(-22, 2.6).y} A 260 260 0 0 1 ${polarPoint(22, 2.6).x} ${polarPoint(22, 2.6).y} Z`} />
          <path className="beam-core" d={`M ${center.x} ${center.y} L ${polarPoint(-4, 2.85).x} ${polarPoint(-4, 2.85).y} A 285 285 0 0 1 ${polarPoint(6, 2.85).x} ${polarPoint(6, 2.85).y} Z`} />
        </g>

        <g className="lidar-points" filter="url(#pointGlow)">
          {lidarPoints.map((point, index) => {
            const p = polarPoint(point.angle, point.distance);
            const hue = point.strength > 0.85 ? "#4cffcb" : point.strength > 0.58 ? "#19d5ff" : "#1498ff";
            return (
              <circle
                key={`${point.angle}-${point.distance}-${index}`}
                cx={p.x}
                cy={p.y}
                r={2.3 + point.strength * 3.2}
                fill={hue}
                opacity={0.28 + point.strength * 0.7}
              />
            );
          })}
        </g>

        <g className="car-marker">
          <path d="M398 330 L404 306 Q420 292 436 306 L442 330 Z" />
          <rect x="402" y="315" width="36" height="34" rx="7" />
          <line x1="420" y1="300" x2="420" y2="282" />
          <path d="M410 338 H430" />
        </g>
      </svg>
    </HudPanel>
  );
}
