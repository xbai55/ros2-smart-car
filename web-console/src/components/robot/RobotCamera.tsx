import { Camera, Eye, ScanEye, Video } from "lucide-react";
import { useEffect, useState } from "react";
import { cn } from "../../lib/cn";
import { shouldStartVideo, videoStateAfterTimeout, type VideoState } from "../../videoState";
import type { Robot } from "../../types/domain";

type Props = { robot: Robot; className?: string };

const DETECTIONS = [
  { label: "人员", confidence: 97, x: 22, y: 30, w: 26, h: 48, tone: "warn" },
  { label: "护目镜未佩戴", confidence: 92, x: 26, y: 14, w: 18, h: 12, tone: "danger" },
  { label: "试剂瓶", confidence: 81, x: 62, y: 44, w: 20, h: 24, tone: "ok" },
];

export function RobotCamera({ robot, className }: Props) {
  const [state, setState] = useState<VideoState>("loading");
  const [revision, setRevision] = useState(0);
  const [overlay, setOverlay] = useState(true);
  const [cameraIndex, setCameraIndex] = useState(0);
  const [streamActive, setStreamActive] = useState(() => shouldStartVideo(document.readyState));

  useEffect(() => {
    const start = () => setStreamActive(true);
    if (shouldStartVideo(document.readyState)) { start(); return; }
    window.addEventListener("load", start, { once: true });
    return () => window.removeEventListener("load", start);
  }, [revision]);

  useEffect(() => {
    if (!streamActive || state !== "loading") return;
    const timer = window.setTimeout(() => setState(videoStateAfterTimeout(state)), 6000);
    return () => window.clearTimeout(timer);
  }, [revision, state, streamActive]);

  const cameras = ["前视", "后视", "俯视"];

  return (
    <div className={cn("camera-workspace", className)}>
      <div className="camera-head">
        <div className="camera-title">
          <Camera size={15} />
          <span>实时视频</span>
          <span className={cn("camera-state", state)}>{state === "connected" ? "在线" : state === "error" ? "无信号" : "连接中"}</span>
        </div>
        <div className="camera-tools">
          <button type="button" className={cn("camera-tool", overlay && "on")} onClick={() => setOverlay((v) => !v)} title="AI 检测叠加">
            <ScanEye size={15} />检测
          </button>
          <button type="button" className="camera-tool" onClick={() => { setState("loading"); setRevision((v) => v + 1); }} title="重连视频">
            <Video size={15} />重连
          </button>
        </div>
      </div>

      <div className="camera-frame">
        {streamActive && state !== "error" ? (
          <img key={revision} className="camera-feed" src={`/video_feed?revision=${revision}`} alt="机器人实时画面" onLoad={() => setState("connected")} onError={() => setState("error")} />
        ) : null}
        {state !== "connected" ? (
          <div className="camera-fallback">
            <Camera size={30} strokeWidth={1.5} />
            <strong>{state === "error" ? "摄像头无信号" : "正在连接视频流…"}</strong>
            <span>视频来自后端 /video_feed</span>
          </div>
        ) : null}
        {overlay && state === "connected" ? (
          <div className="detection-overlay" aria-label="AI 检测框">
            {DETECTIONS.map((d) => (
              <div key={d.label} className={cn("detection-box", d.tone)} style={{ left: `${d.x}%`, top: `${d.y}%`, width: `${d.w}%`, height: `${d.h}%` }}>
                <span className="detection-tag">{d.label} {d.confidence}%</span>
              </div>
            ))}
          </div>
        ) : null}
        <div className="camera-badge">
          <span className={cn("camera-badge-dot", state === "connected" ? "live" : "")} />
          {robot.name} · {cameraIndex === 0 ? "前视" : cameraIndex === 1 ? "后视" : "俯视"}
        </div>
      </div>

      <div className="camera-strip">
        {cameras.map((cam, i) => (
          <button key={cam} type="button" className={cn("camera-strip-item", i === cameraIndex && "active")} onClick={() => setCameraIndex(i)}>
            <Eye size={14} />
            {cam}
          </button>
        ))}
        <span className="camera-strip-hint">YOLO · ByteTrack 跟踪中</span>
      </div>
    </div>
  );
}
