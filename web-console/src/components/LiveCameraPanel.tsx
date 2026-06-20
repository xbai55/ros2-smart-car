import { Camera, RefreshCcw } from "lucide-react";
import { useEffect, useState } from "react";
import { VIDEO_START_TIMEOUT_MS, shouldStartVideo, videoStateAfterTimeout, type VideoState } from "../videoState";
import { HudPanel } from "./HudPanel";

export type { VideoState } from "../videoState";
type Props = { revision: number; state: VideoState; onStateChange: (state: VideoState) => void; onReconnect: () => void };

export function LiveCameraPanel({ revision, state, onStateChange, onReconnect }: Props) {
  const [streamActive, setStreamActive] = useState(() => shouldStartVideo(document.readyState));

  useEffect(() => {
    const start = () => setStreamActive(true);
    if (shouldStartVideo(document.readyState)) {
      start();
      return;
    }
    window.addEventListener("load", start, { once: true });
    return () => window.removeEventListener("load", start);
  }, [revision]);
  useEffect(() => {
    if (!streamActive || state !== "loading") return;
    const timer = window.setTimeout(() => onStateChange(videoStateAfterTimeout(state)), VIDEO_START_TIMEOUT_MS);
    return () => window.clearTimeout(timer);
  }, [revision, state, streamActive, onStateChange]);

  return (
    <HudPanel className="live-camera" title="Live Camera" subtitle="现场画面" action={
      <button className="ghost-btn" type="button" onClick={onReconnect} title="重新连接视频流">
        <RefreshCcw size={15} />
        {state === "loading" ? "正在连接..." : "重连视频"}
      </button>
    }>
      <div className="video-frame">
        {streamActive && state !== "error" ? (
          <img
            key={revision}
            className="camera-feed"
            src={`/video_feed?revision=${revision}`}
            alt="小车实时摄像头画面"
            onLoad={() => onStateChange("connected")}
            onError={() => onStateChange("error")}
          />
        ) : null}
        {state !== "connected" ? (
          <div className="video-hud">
            <div className="camera-state">
              <Camera size={34} />
              <strong>{state === "error" ? "摄像头连接失败" : "正在等待第一帧"}</strong>
              <span>{state === "error" ? "6 秒内未收到视频帧，请检查 USB 摄像头" : "视频来自后端 /video_feed"}</span>
            </div>
          </div>
        ) : null}
        <div className="video-meta left">
          <span className={`status-dot ${state === "connected" ? "green" : ""}`} />
          <span>{state === "connected" ? "视频已连接" : state === "error" ? "视频无帧" : "等待视频"}</span>
        </div>
        <div className="video-meta right">/video_feed</div>
      </div>
    </HudPanel>
  );
}

