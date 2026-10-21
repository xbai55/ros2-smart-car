import { Crosshair, Download, Layers, LocateFixed, Map, Minus, Moon, Plus, Sun } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { useRobotStream } from "../../hooks/useRobotStream";
import { mapWorldToScreen } from "../../liveControl";
import { cn } from "../../lib/cn";
import { mapScreenToWorld, type Point } from "../../labNavigation";
import { drawingRasterTransform, occupancyColor, rotatedRasterViewport, rotatePoint, viewportToRaster, worldToRaster } from "../../mapLayers";
import { MAP_MARKERS } from "../../mapViewport";
import type { MapSnapshot } from "../../robotApi";

export type DrawingOverlay = { imageUrl: string; width: number; height: number; matrix: number[]; name: string; raster?: boolean };
type Marker = Point & { name: string };
type Props = { className?: string; onPick?: (p: Point) => void; overlay?: DrawingOverlay; path?: Point[]; goal?: Point | null; places?: Marker[]; anchors?: Point[] };

export function LiveMapCanvas({ className, onPick, overlay, path = [], goal, places = [], anchors = [] }: Props) {
  const { mapSnapshot: snapshot, mapError, mapStale, mapSessionKey, initialMapYaw: initialYaw, status, connection } = useRobotStream();
  const container = useRef<HTMLDivElement>(null), canvas = useRef<HTMLCanvasElement>(null);
  const raster = useRef<HTMLCanvasElement | null>(null), obstacles = useRef<HTMLCanvasElement | null>(null);
  const [size, setSize] = useState({ w: 800, h: 480 }), [zoom, setZoom] = useState(1), [pan, setPan] = useState({ x: 0, y: 0 });
  const [theme, setTheme] = useState<"light" | "dark">("light"), [viewMode, setViewMode] = useState<"auto" | "free" | "follow">("auto");
  const [orientation, setOrientation] = useState<"heading" | "map">("heading");
  const [showDrawing, setShowDrawing] = useState(true), [opacity, setOpacity] = useState(.4), [showPath, setShowPath] = useState(true), [showPlaces, setShowPlaces] = useState(true);
  const [drawingImage, setDrawingImage] = useState<HTMLImageElement | null>(null);
  const drag = useRef<{ x: number; y: number; panX: number; panY: number; moved: boolean } | null>(null);
  const frame = `${mapSessionKey}:${snapshot?.session_id ?? ""}:${snapshot?.header?.frame_id || "map"}`;
  const reference = useRef<MapSnapshot | null>(null);
  const previousFrame = useRef(frame);
  if (previousFrame.current !== frame) { reference.current = null; previousFrame.current = frame; }
  if (snapshot && !reference.current) reference.current = { ...snapshot, data: [] };
  useEffect(() => { setZoom(1); setPan({ x: 0, y: 0 }); setViewMode("auto"); drag.current = null; }, [frame]);
  useEffect(() => {
    if (!container.current) return;
    const observer = new ResizeObserver(([entry]) => setSize({ w: Math.max(1, entry.contentRect.width), h: Math.max(1, entry.contentRect.height) }));
    observer.observe(container.current); return () => observer.disconnect();
  }, []);
  useEffect(() => {
    let active = true; setDrawingImage(null);
    if (!overlay?.imageUrl) return;
    const img = new Image(); img.onload = () => { if (active) setDrawingImage(img); }; img.src = overlay.imageUrl;
    return () => { active = false; img.onload = null; };
  }, [overlay?.imageUrl]);
  useEffect(() => {
    if (!snapshot) { raster.current = obstacles.current = null; return; }
    const image = document.createElement("canvas"), solid = document.createElement("canvas");
    image.width = solid.width = snapshot.info.width; image.height = solid.height = snapshot.info.height;
    const ctx = image.getContext("2d"), wall = solid.getContext("2d"); if (!ctx || !wall) return;
    const pixels = ctx.createImageData(image.width, image.height), occupied = wall.createImageData(image.width, image.height);
    for (let y = 0; y < image.height; y++) for (let x = 0; x < image.width; x++) {
      const value = snapshot.data[y * image.width + x], i = ((image.height - y - 1) * image.width + x) * 4;
      const color = occupancyColor(value, theme); pixels.data.set(color, i);
      if (value >= 25) occupied.data.set(color, i);
    }
    ctx.putImageData(pixels, 0, 0); wall.putImageData(occupied, 0, 0); raster.current = image; obstacles.current = solid;
  }, [snapshot, theme]);
  const rotation = snapshot ? orientation === "heading" && initialYaw !== null ? initialYaw - snapshot.info.origin.yaw - Math.PI / 2 : -snapshot.info.origin.yaw : 0;
  const basis = viewMode === "auto" ? snapshot : reference.current;
  const viewport = snapshot && basis ? rotatedRasterViewport(snapshot, basis, size, zoom, { x: 0, y: 0 }, rotation) : { scale: 1, offset: { x: 0, y: 0 } };
  const scale = viewport.scale, baseOffset = viewport.offset;
  const robotPoint = snapshot && connection === "connected" && status.map_pose.ok ? mapWorldToScreen(snapshot, status.map_pose) : null;
  const offset = viewMode === "follow" && robotPoint && snapshot ? rotatePoint({ x: (snapshot.info.width / 2 - robotPoint.x) * scale, y: (snapshot.info.height / 2 - robotPoint.y) * scale }, rotation) : { x: baseOffset.x + pan.x, y: baseOffset.y + pan.y };
  useEffect(() => {
    const element = canvas.current; if (!element) return;
    const dpr = window.devicePixelRatio || 1; element.width = Math.round(size.w * dpr); element.height = Math.round(size.h * dpr);
    const ctx = element.getContext("2d"); if (!ctx) return;
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0); ctx.fillStyle = theme === "light" ? "#f1f5f9" : "#101b2b"; ctx.fillRect(0, 0, size.w, size.h);
    ctx.strokeStyle = theme === "light" ? "#e2e8f0" : "#203049"; ctx.lineWidth = .5;
    for (let x = 0; x < size.w; x += 32) { ctx.beginPath(); ctx.moveTo(x, 0); ctx.lineTo(x, size.h); ctx.stroke(); }
    for (let y = 0; y < size.h; y += 32) { ctx.beginPath(); ctx.moveTo(0, y); ctx.lineTo(size.w, y); ctx.stroke(); }
    if (!snapshot || !raster.current) return;
    ctx.translate(size.w / 2 + offset.x, size.h / 2 + offset.y); ctx.rotate(rotation); ctx.scale(scale, scale); ctx.translate(-snapshot.info.width / 2, -snapshot.info.height / 2);
    ctx.imageSmoothingEnabled = false; ctx.drawImage(raster.current, 0, 0);
    if (showDrawing && overlay && drawingImage) {
      ctx.save(); ctx.transform(...drawingRasterTransform(snapshot, overlay.matrix)); ctx.globalAlpha = opacity; ctx.imageSmoothingEnabled = !overlay.raster;
      ctx.drawImage(drawingImage, 0, 0, overlay.width, overlay.height); ctx.restore();
      // Always keep measured obstacles above the reference drawing.
      if (obstacles.current) { ctx.imageSmoothingEnabled = false; ctx.drawImage(obstacles.current, 0, 0); }
    }
    if (showPath && path.length > 1) {
      ctx.beginPath(); path.forEach((p, i) => { const v = worldToRaster(snapshot, p); if (i) ctx.lineTo(v.x, v.y); else ctx.moveTo(v.x, v.y); });
      ctx.strokeStyle = "#ffffff"; ctx.lineWidth = 7 / scale; ctx.lineJoin = ctx.lineCap = "round"; ctx.stroke(); ctx.strokeStyle = "#2563eb"; ctx.lineWidth = 3 / scale; ctx.stroke();
    }
    if (showPlaces) places.forEach(p => {
      const v = worldToRaster(snapshot, p); ctx.save(); ctx.translate(v.x, v.y); ctx.rotate(-rotation);
      ctx.beginPath(); ctx.arc(0, 0, 5 / scale, 0, Math.PI * 2); ctx.fillStyle = "#0f766e"; ctx.fill();
      ctx.font = `${12 / scale}px sans-serif`; ctx.lineWidth = 3 / scale; ctx.strokeStyle = "#ffffff"; ctx.strokeText(p.name, 9 / scale, -7 / scale); ctx.fillStyle = "#0f172a"; ctx.fillText(p.name, 9 / scale, -7 / scale); ctx.restore();
    });
    anchors.forEach((p, i) => { const v = worldToRaster(snapshot, p); ctx.beginPath(); ctx.arc(v.x, v.y, 12 / scale, 0, Math.PI * 2); ctx.fillStyle = "#fef3c7"; ctx.fill(); ctx.strokeStyle = "#b45309"; ctx.lineWidth = 2 / scale; ctx.stroke(); ctx.fillStyle = "#92400e"; ctx.font = `bold ${12 / scale}px sans-serif`; ctx.textAlign = "center"; ctx.textBaseline = "middle"; ctx.fillText(String(i + 1), v.x, v.y); ctx.textAlign = "start"; ctx.textBaseline = "alphabetic"; });
    if (goal) { const v = worldToRaster(snapshot, goal); ctx.beginPath(); ctx.arc(v.x, v.y, 11 / scale, 0, Math.PI * 2); ctx.fillStyle = "#16a34a30"; ctx.fill(); ctx.strokeStyle = "#15803d"; ctx.lineWidth = 2 / scale; ctx.stroke(); ctx.beginPath(); ctx.arc(v.x, v.y, 4 / scale, 0, Math.PI * 2); ctx.fillStyle = "#15803d"; ctx.fill(); }
    if (robotPoint) {
      ctx.save(); ctx.translate(robotPoint.x, robotPoint.y); ctx.rotate(robotPoint.yawDeg * Math.PI / 180);
      const r = MAP_MARKERS.robot / scale; ctx.beginPath(); ctx.arc(0, 0, MAP_MARKERS.halo / scale, 0, Math.PI * 2); ctx.fillStyle = "#2563eb24"; ctx.fill();
      ctx.fillStyle = "#2563eb"; ctx.strokeStyle = "#ffffff"; ctx.lineWidth = 2 / scale; ctx.beginPath(); ctx.moveTo(r, 0); ctx.lineTo(-r * .7, -r * .7); ctx.lineTo(-r * .35, 0); ctx.lineTo(-r * .7, r * .7); ctx.closePath(); ctx.fill(); ctx.stroke(); ctx.restore();
    }
  }, [size, scale, offset.x, offset.y, rotation, snapshot, theme, drawingImage, overlay, opacity, showDrawing, showPath, showPlaces, path, places, anchors, goal, robotPoint?.x, robotPoint?.y, robotPoint?.yawDeg]);
  const enterFreeView = () => {
    if (viewMode === "auto" && snapshot) reference.current = { ...snapshot, data: [] };
    setViewMode("free");
  };
  const changeZoom = (factor: number) => { enterFreeView(); setPan({ x: offset.x - baseOffset.x, y: offset.y - baseOffset.y }); setZoom(z => Math.max(.25, Math.min(8, z * factor))); };
  useEffect(() => {
    const element = canvas.current; if (!element) return;
    const wheel = (e: WheelEvent) => { if (!snapshot) return; e.preventDefault(); changeZoom(e.deltaY < 0 ? 1.15 : 1 / 1.15); };
    element.addEventListener("wheel", wheel, { passive: false }); return () => element.removeEventListener("wheel", wheel);
  }, [snapshot, viewMode, offset.x, offset.y, baseOffset.x, baseOffset.y]);
  const reset = () => { reference.current = snapshot ? { ...snapshot, data: [] } : null; setViewMode("auto"); setZoom(1); setPan({ x: 0, y: 0 }); };
  const exportImage = () => { if (!canvas.current || !snapshot) return; const link = document.createElement("a"); link.download = "slam-map-view.png"; link.href = canvas.current.toDataURL("image/png"); link.click(); };
  return <div className={cn("live-map-view", theme === "light" && "map-light", className)}>
    <div className="live-map-toolbar"><span><Map size={14}/>{snapshot ? "SLAM 实时地图" : "地图待接入"}</span><div>
      <button aria-label="缩小地图" onClick={() => changeZoom(1 / 1.25)} disabled={!snapshot}><Minus size={15}/></button><span>{Math.round(zoom * 100)}%</span>
      <button aria-label="放大地图" onClick={() => changeZoom(1.25)} disabled={!snapshot}><Plus size={15}/></button>
      <button aria-label="适配地图" aria-pressed={viewMode === "auto"} onClick={reset} disabled={!snapshot}><Crosshair size={15}/>自动适配</button>
      <button aria-label="跟随小车" aria-pressed={viewMode === "follow"} onClick={() => { if (viewMode === "follow") reset(); else { reference.current = snapshot ? { ...snapshot, data: [] } : null; setViewMode("follow"); } }} disabled={!robotPoint}><LocateFixed size={15}/></button>
      <button aria-label="切换地图显示方向" aria-pressed={orientation === "heading"} onClick={() => { setOrientation(v => v === "heading" ? "map" : "heading"); reset(); }}>{orientation === "heading" ? "初始车头朝上" : "地图坐标方向"}</button>
      <button aria-label={theme === "light" ? "切换深色地图" : "切换浅色地图"} onClick={() => setTheme(v => v === "light" ? "dark" : "light")}>{theme === "light" ? <Moon size={15}/> : <Sun size={15}/>}</button>
      <button aria-label="导出地图视图 PNG" onClick={exportImage} disabled={!snapshot}><Download size={15}/></button>
    </div></div>
    {(overlay || path.length > 0 || places.length > 0) && <div className="map-layer-controls"><span><Layers size={14}/>图层</span>
      {overlay && <><label><input type="checkbox" checked={showDrawing} onChange={e => setShowDrawing(e.target.checked)}/>平面图</label><label className="map-opacity">透明度<input aria-label="平面图透明度" type="range" min={.1} max={.8} step={.05} value={opacity} onChange={e => setOpacity(Number(e.target.value))}/></label></>}
      {path.length > 0 && <label><input type="checkbox" checked={showPath} onChange={e => setShowPath(e.target.checked)}/>路线</label>}
      {places.length > 0 && <label><input type="checkbox" checked={showPlaces} onChange={e => setShowPlaces(e.target.checked)}/>地点</label>}
      <small>障碍来自 SLAM</small>
    </div>}
    <div className="live-map-stage" ref={container}>
      <canvas ref={canvas} role="img" aria-label="真实 SLAM 地图，可拖动缩放，Alt 加方向键平移，R 自动适配；方向键驾驶" tabIndex={0}
        onPointerDown={e => { if (!snapshot) return; e.currentTarget.setPointerCapture(e.pointerId); drag.current = { x: e.clientX, y: e.clientY, panX: offset.x - baseOffset.x, panY: offset.y - baseOffset.y, moved: false }; }}
        onPointerMove={e => { const d = drag.current; if (d && Math.hypot(e.clientX - d.x, e.clientY - d.y) > 6) { d.moved = true; enterFreeView(); setPan({ x: d.panX + e.clientX - d.x, y: d.panY + e.clientY - d.y }); } }}
        onPointerUp={e => { const d = drag.current; drag.current = null; if (d && snapshot && onPick && !d.moved) { const r = e.currentTarget.getBoundingClientRect(); onPick(mapScreenToWorld(snapshot, viewportToRaster({ x: e.clientX - r.left, y: e.clientY - r.top }, snapshot, size, scale, offset, rotation))); } }}
        onPointerCancel={() => { drag.current = null; }} onLostPointerCapture={() => { drag.current = null; }}
        onKeyDown={e => { if (e.ctrlKey || e.metaKey) return; if (e.altKey && ["ArrowLeft", "ArrowRight", "ArrowUp", "ArrowDown"].includes(e.key)) { e.preventDefault(); enterFreeView(); setPan({ x: offset.x - baseOffset.x + (e.key === "ArrowLeft" ? 20 : e.key === "ArrowRight" ? -20 : 0), y: offset.y - baseOffset.y + (e.key === "ArrowUp" ? 20 : e.key === "ArrowDown" ? -20 : 0) }); } if (!e.altKey && e.key.toLowerCase() === "r") { e.preventDefault(); reset(); } }}/>
      {!snapshot && <div className="live-map-empty"><Map size={34} strokeWidth={1.4}/><strong>{connection !== "connected" ? "等待小车连接" : status.mapping.state === "error" ? "建图启动失败" : status.mapping.state === "starting" ? "正在启动建图进程" : status.mapping.state === "waiting_map" ? "等待首张有效地图" : mapError ? "地图读取失败" : status.mapping.state === "ready" ? "正在读取本轮地图" : status.mode === "mapping" ? "等待首张有效地图" : "尚无实车地图"}</strong><span>{status.mapping.error || mapError || "启动 SLAM 建图后，这里将显示真实环境地图"}</span>{status.mapping.started_at && (status.mapping.state === "starting" || status.mapping.state === "waiting_map") ? <span>本轮已等待 {Math.max(0, Math.floor(Date.now() / 1000 - status.mapping.started_at))} 秒</span> : null}</div>}
      {snapshot && <><div className="live-map-scale"><i style={{ width: Math.max(1, Math.min(140, scale / snapshot.info.resolution)) }}/><span>{(Math.min(140, scale / snapshot.info.resolution) * snapshot.info.resolution / scale).toFixed(2)} m</span></div><span className="live-map-pose">{mapStale ? "地图已过期 · 显示最近画面" : robotPoint ? viewMode === "follow" ? "跟随小车" : viewMode === "auto" ? "自动适配 · 定位有效" : "自由视图 · 定位有效" : "等待地图定位"}</span></>}
    </div>
    <div className="live-map-footer"><span><i className="legend-dot free"/>可通行</span><span><i className="legend-dot wall"/>障碍</span><span><i className="legend-dot unknown"/>未知</span><span>{mapError && snapshot ? mapError : snapshot ? `${snapshot.info.width} × ${snapshot.info.height} · ${snapshot.info.resolution.toFixed(3)} m/格${orientation === "heading" && initialYaw === null ? " · 等待初始朝向" : ""}` : "等待真实数据"}</span></div>
  </div>;
}
