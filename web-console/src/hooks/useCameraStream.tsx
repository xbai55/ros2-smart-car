import { createContext, useCallback, useContext, useEffect, useLayoutEffect, useRef, useState, type ReactNode } from "react";
import { startCameraPolling } from "../cameraPolling";
import type { VideoState } from "../videoState";

type Stream = { state: VideoState; attach: (host: HTMLElement) => () => void; start: () => void; reconnect: () => void };
const CameraContext = createContext<Stream | null>(null);

// Keep one image and one request loop above the router, shared across pages.
export function CameraStreamProvider({ children }: { children: ReactNode }) {
  const parking = useRef<HTMLDivElement>(null);
  const [feed] = useState(() => {
    const img = document.createElement("img");
    img.className = "camera-feed";
    img.alt = "智巡一号摄像头实时画面";
    return img;
  });
  const [state, setState] = useState<VideoState>("loading");
  const [generation, setGeneration] = useState(0);
  const [active, setActive] = useState(false);
  const started = useRef(false);
  const reconnect = useCallback(() => {
    started.current = true;
    setState("loading");
    setGeneration(value => value + 1);
  }, []);
  const start = useCallback(() => { if (!started.current) reconnect(); }, [reconnect]);

  useEffect(() => {
    if (!feed.parentElement) parking.current?.appendChild(feed);
    return () => { feed.removeAttribute("src"); feed.remove(); };
  }, [feed]);

  useEffect(() => {
    if (!generation || !active) return;
    let url: string | undefined;
    const polling = startCameraPolling({
      visible: document.visibilityState !== "hidden",
      onState: setState,
      fetchFrame: async signal => {
        const response = await fetch(`/api/video?frame=true&revision=${generation}`, { signal, cache: "no-store" });
        if (!response.ok || !response.headers.get("Content-Type")?.includes("image/jpeg")) throw new Error("camera_frame_unavailable");
        return response.blob();
      },
      display: (frame, signal) => new Promise<void>((resolve, reject) => {
        const nextUrl = URL.createObjectURL(frame);
        const previousUrl = url;
        const cleanup = () => { feed.onload = null; feed.onerror = null; signal.removeEventListener("abort", abort); };
        const abort = () => { cleanup(); URL.revokeObjectURL(nextUrl); reject(new Error("camera_frame_cancelled")); };
        feed.onload = () => {
          cleanup();
          if (previousUrl) URL.revokeObjectURL(previousUrl);
          url = nextUrl;
          resolve();
        };
        feed.onerror = abort;
        signal.addEventListener("abort", abort, { once: true });
        feed.src = nextUrl;
      }),
    });
    const visibility = () => polling.setVisible(document.visibilityState !== "hidden");
    document.addEventListener("visibilitychange", visibility);
    return () => {
      polling.stop();
      document.removeEventListener("visibilitychange", visibility);
      if (url) URL.revokeObjectURL(url);
    };
  }, [active, generation, feed]);

  const attach = useCallback((host: HTMLElement) => {
    host.appendChild(feed);
    setActive(true);
    return () => {
      if (feed.parentElement === host) parking.current?.appendChild(feed);
      // A route change can attach the same image in this commit: keep its loop.
      queueMicrotask(() => { if (feed.parentElement === parking.current) setActive(false); });
    };
  }, [feed]);
  return <CameraContext.Provider value={{ state, attach, start, reconnect }}>
    <div ref={parking} style={{ display: "none" }} aria-hidden="true" />
    {children}
  </CameraContext.Provider>;
}

export function useCameraStream(enabled: boolean) {
  const stream = useContext(CameraContext);
  if (!stream) throw new Error("CameraStreamProvider is required");
  const host = useRef<HTMLDivElement>(null);
  useLayoutEffect(() => { if (enabled && host.current) return stream.attach(host.current); }, [enabled, stream.attach]);
  useEffect(() => { if (enabled) stream.start(); }, [enabled, stream.start]);
  return { host, state: stream.state, reconnect: stream.reconnect };
}
