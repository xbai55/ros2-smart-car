import { useEffect, useMemo, useRef, useState } from "react";
import {
  Activity,
  AlertTriangle,
  CheckCircle2,
  Grid3X3,
  Layers,
  Map,
  RotateCcw,
  Ruler,
  Save,
  TimerReset,
} from "lucide-react";
import {
  cellColor,
  enhancedDisplayValue,
  GRID_STROKE_COLOR,
  shouldRemoveObstacleNoise,
  stableSquareViewBox,
  UNKNOWN_COLOR,
} from "../mapDisplay";
import {
  applySlamCorrection,
  hasActiveVelocity,
  isDriveCommand,
  mapPoseToScreenCell,
  projectPoseByCommand,
  projectPoseByVelocity,
  scaleCommandProjectionSpeed,
  shouldApplySlamCorrection,
  slamCorrectionTuning,
  smoothMapPoseCell,
  type DisplayPoseCell,
  type MapFrame,
} from "../mapPoseSmoothing";
import {
  createRobotApi,
  type LidarHealth,
  type MapHealth,
  type MapPose,
  type MapSnapshot,
  type MappingQuality,
  type CmdVelStatus,
  type OdomHealth,
  type TfHealth,
} from "../robotApi";
import { HudPanel } from "./HudPanel";

type MapPanelProps = {
  map: MapHealth;
  lidar: LidarHealth;
  odom: OdomHealth;
  cmdVel: CmdVelStatus;
  tf: TfHealth;
  mapPose: MapPose;
  mappingQuality: MappingQuality;
  lastCommand: string;
  active: boolean;
  speed: number;
  restarting?: boolean;
  saving?: boolean;
  savePath?: string;
  onRestart?: () => void;
  onSave?: () => void;
};

type MapViewMode = "enhanced" | "raw";
type QualityTone = "good" | "warn" | "bad";

function calculateNoiseRatio(cells: number[], width: number, height: number) {
  let occupied = 0;
  let isolated = 0;
  cells.forEach((value, index) => {
    if (value < 65) return;
    occupied += 1;
    const x = index % width;
    const y = Math.floor(index / width);
    if (shouldRemoveObstacleNoise(cells, width, height, x, y)) isolated += 1;
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

function mapFrame(snapshot: MapSnapshot): MapFrame {
  return {
    width: snapshot.info.width,
    height: snapshot.info.height,
    resolution: snapshot.info.resolution || 0.05,
    originX: snapshot.info.origin.x,
    originY: snapshot.info.origin.y,
  };
}

function mapFrameKey(frame: MapFrame | null) {
  if (!frame) return "";
  return `${frame.width}:${frame.height}:${frame.resolution}:${frame.originX.toFixed(3)}:${frame.originY.toFixed(3)}`;
}

export function MapPanel({
  map,
  lidar,
  odom,
  cmdVel,
  tf,
  mapPose,
  mappingQuality,
  lastCommand,
  active,
  speed,
  restarting = false,
  saving = false,
  savePath = "",
  onRestart,
  onSave,
}: MapPanelProps) {
  const api = useMemo(() => createRobotApi(), []);
  const [snapshot, setSnapshot] = useState<MapSnapshot | null>(null);
  const [error, setError] = useState("");
  const [viewMode, setViewMode] = useState<MapViewMode>("enhanced");
  const [slamCorrectionEnabled, setSlamCorrectionEnabled] = useState(false);
  const [slamCorrectionStatus, setSlamCorrectionStatus] = useState<"off" | "hold" | "attract" | "snap">("off");
  const [displayPoseCell, setDisplayPoseCell] = useState<DisplayPoseCell | null>(null);
  const displayPoseRef = useRef<DisplayPoseCell | null>(null);
  const slamPoseRef = useRef<DisplayPoseCell | null>(null);
  const slamPoseChangedRef = useRef(false);
  const tickTimeRef = useRef<number | null>(null);
  const mapFrameKeyRef = useRef("");

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
    if (!map.ok && map.message === "restarting") {
      setSnapshot(null);
      setDisplayPoseCell(null);
      displayPoseRef.current = null;
      slamPoseRef.current = null;
      tickTimeRef.current = null;
      mapFrameKeyRef.current = "";
    }
  }, [map.message, map.ok]);

  useEffect(() => {
    if (!snapshot || !mapPose.ok) {
      slamPoseRef.current = null;
      return;
    }

    const frame = mapFrame(snapshot);
    const nextFrameKey = mapFrameKey(frame);
    const frameChanged = mapFrameKeyRef.current !== "" && mapFrameKeyRef.current !== nextFrameKey;
    mapFrameKeyRef.current = nextFrameKey;

    const previousSlamPose = slamPoseRef.current;
    const nextPose = mapPoseToScreenCell(frame, mapPose);
    slamPoseChangedRef.current = !previousSlamPose
      || Math.hypot(nextPose.x - previousSlamPose.x, nextPose.y - previousSlamPose.y) > 0.05
      || Math.abs((nextPose.motionYawDeg ?? nextPose.yawDeg) - (previousSlamPose.motionYawDeg ?? previousSlamPose.yawDeg)) > 0.5;
    slamPoseRef.current = nextPose;
    if (frameChanged || !displayPoseRef.current) {
      displayPoseRef.current = nextPose;
      setDisplayPoseCell(nextPose);
    }
  }, [snapshot, mapPose.ok, mapPose.x, mapPose.y, mapPose.yaw, mapPose.updated_at]);

  useEffect(() => {
    const timer = window.setInterval(() => {
      const now = window.performance.now();
      const previousTick = tickTimeRef.current ?? now;
      tickTimeRef.current = now;
      const deltaSeconds = Math.min(0.2, Math.max(0, (now - previousTick) / 1000));
      const slamPose = slamPoseRef.current;
      const currentPose = displayPoseRef.current ?? slamPose;
      if (!currentPose) return;

      const resolution = snapshot?.info.resolution || map.resolution || 0.05;
      const hasFreshCmdVel = cmdVel.ok && hasActiveVelocity(cmdVel);
      const nominalSpeedCellsPerSecond = Math.max(0.02, (speed / 100) * 0.28) / resolution;
      const deadReckonedPose = hasFreshCmdVel
        ? projectPoseByVelocity(currentPose, cmdVel, deltaSeconds, resolution)
        : isDriveCommand(lastCommand)
          ? projectPoseByCommand(
            currentPose,
            lastCommand,
            deltaSeconds,
            scaleCommandProjectionSpeed(lastCommand, nominalSpeedCellsPerSecond),
          )
          : currentPose;
      const isMovingDisplay = hasFreshCmdVel || isDriveCommand(lastCommand);
      const correctionTuning = slamCorrectionTuning(lastCommand, isMovingDisplay);
      const canApplySlamCorrection = shouldApplySlamCorrection(
        slamCorrectionEnabled,
        slamPoseChangedRef.current,
        lastCommand,
        cmdVel,
      );
      const corrected = slamPose
        ? applySlamCorrection(deadReckonedPose, slamPose, canApplySlamCorrection, {
          // Correct drift while driving so the marker does not visibly pull back
          // after the user releases the command.
          alpha: correctionTuning.alpha,
          attractDistanceCells: correctionTuning.attractDistanceCells,
          snapDistanceCells: correctionTuning.snapDistanceCells,
        })
        : { pose: deadReckonedPose, status: "off" as const };

      setSlamCorrectionStatus(slamCorrectionEnabled && !slamPoseChangedRef.current ? "hold" : corrected.status);
      displayPoseRef.current = corrected.pose;
      setDisplayPoseCell((previous) => smoothMapPoseCell(previous, corrected.pose, {
        teleportDistanceCells: 18,
        positionAlpha: correctionTuning.positionAlpha,
        yawAlpha: correctionTuning.yawAlpha,
      }));
    }, 50);
    return () => window.clearInterval(timer);
  }, [
    cmdVel.angular_z,
    cmdVel.linear_x,
    cmdVel.linear_y,
    cmdVel.ok,
    lastCommand,
    map.resolution,
    slamCorrectionEnabled,
    snapshot?.info.resolution,
    speed,
  ]);

  const width = snapshot?.info.width ?? map.width;
  const height = snapshot?.info.height ?? map.height;
  const resolution = snapshot?.info.resolution ?? map.resolution;
  const cells = snapshot?.data ?? [];
  const viewBox = stableSquareViewBox(width, height);
  const updatedAge = snapshot ? Math.max(0, Date.now() / 1000 - snapshot.updated_at) : null;
  const noiseRatio = snapshot ? calculateNoiseRatio(cells, width, height) : null;
  const quality = qualityLabel(map, lidar, speed, noiseRatio);
  const speedOk = speed <= 25;
  const restartBlocked = !lidar.ok || !odom.ok || !tf.ok;
  const restartBlockReason = [
    !lidar.ok ? "SCAN" : "",
    !odom.ok ? "ODOM" : "",
    !tf.ok ? "TF" : "",
  ].filter(Boolean).join("/");

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
          <button type="button" onClick={onRestart} disabled={!onRestart || restarting || restartBlocked}>
            <RotateCcw size={14} />{restarting ? "重启中" : "重启建图"}
          </button>
          <button type="button" onClick={onSave} disabled={!onSave || saving || !map.ok}>
            <Save size={14} />{saving ? "保存中" : "保存地图"}
          </button>
          <button type="button" onClick={() => setViewMode((mode) => mode === "enhanced" ? "raw" : "enhanced")}>
            <Layers size={14} />{viewMode === "enhanced" ? "切到原始" : "切到美化"}
          </button>
          <button
            type="button"
            className={slamCorrectionEnabled ? "active" : ""}
            aria-pressed={slamCorrectionEnabled}
            onClick={() => setSlamCorrectionEnabled((enabled) => !enabled)}
          >
            <Activity size={14} />SLAM {slamCorrectionEnabled ? "ON" : "OFF"}
          </button>
        </div>
      </div>

      <div className="map-health-strip">
        <span className={statusClass(lidar.ok)}>{lidar.ok ? <CheckCircle2 size={13} /> : <AlertTriangle size={13} />} SCAN</span>
        <span className={statusClass(map.ok)}>{map.ok ? <CheckCircle2 size={13} /> : <AlertTriangle size={13} />} MAP</span>
        <span className={statusClass(odom.ok)}>{odom.ok ? <CheckCircle2 size={13} /> : <AlertTriangle size={13} />} ODOM</span>
        <span className={statusClass(tf.ok)}>{tf.ok ? <CheckCircle2 size={13} /> : <AlertTriangle size={13} />} TF</span>
        <span className={statusClass(speedOk)}>{speedOk ? <CheckCircle2 size={13} /> : <AlertTriangle size={13} />} {speed}%</span>
        <span className={mappingQuality.level}><Activity size={13} /> 建图质量 {mappingQuality.level}</span>
        <span className={slamCorrectionEnabled ? "ok" : ""}>SLAM {slamCorrectionStatus}</span>
        <b>{restartBlocked ? `重启风险: ${restartBlockReason}` : quality.detail}</b>
      </div>

      <div className="mapping-guide">
        <span>静止初始化 5 秒</span>
        <span>低速前进</span>
        <span>小角度转向</span>
        <span>停止等待地图更新</span>
        {speedOk ? <b>速度正常</b> : <b className="warn">速度过高，建议降到 25% 以下</b>}
      </div>

      <div className="map-canvas" role="img" aria-label="SLAM 二维占据栅格地图">
        {snapshot ? (
          <svg viewBox={viewBox} preserveAspectRatio="xMidYMid meet" className={viewMode === "enhanced" ? "map-enhanced" : "map-raw"}>
            <rect width={width} height={height} fill={UNKNOWN_COLOR} />
            <g>
              {cells.map((value, index) => {
                const x = index % width;
                const y = Math.floor(index / width);
                const screenY = height - y - 1;
                const displayValue = viewMode === "enhanced" ? enhancedDisplayValue(cells, width, height, x, y) : value;
                return (
                  <rect
                    key={index}
                    x={x}
                    y={screenY}
                    width={1}
                    height={1}
                    fill={cellColor(displayValue)}
                    stroke={GRID_STROKE_COLOR}
                    strokeWidth={0.035}
                  />
                );
              })}
              {displayPoseCell ? (
                <g
                  className="map-car-marker"
                  transform={`translate(${displayPoseCell.x} ${displayPoseCell.y}) rotate(${displayPoseCell.yawDeg}) scale(0.105)`}
                >
                  <path className="map-car-hood" d="M 0 -22 L 24 -16 Q 38 0 24 16 L 0 22 Z" />
                  <rect className="map-car-body" x="-19" y="-18" width="36" height="36" rx="7" />
                  <line className="map-car-front-line" x1="30" y1="0" x2="50" y2="0" />
                  <path className="map-car-window" d="M -8 -10 H 9 Q 18 -6 21 0 Q 18 6 9 10 H -8 Z" />
                </g>
              ) : null}
            </g>
          </svg>
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
      {savePath ? <div className="map-save-path">保存路径: {savePath}</div> : null}
    </HudPanel>
  );
}
