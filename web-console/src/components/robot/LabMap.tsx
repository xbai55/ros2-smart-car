import { useEffect, useRef, useState } from "react";
import { Crosshair, Minus, Plus } from "lucide-react";
import { LAB, LAB_BARRIERS, BUILTIN_DRAWING, type DrawingDescriptor, type Point, type Place } from "../../labNavigation";
import { MAP_MARKERS, svgScreenScale } from "../../mapViewport";

type Props = { goal: Point | null; path: Point[]; robot: (Point & { yaw: number }) | null; places: Place[];
  onPick: (point: Point) => void; disabled?: boolean; anchors?: Point[]; calibrating?: boolean; drawing?: DrawingDescriptor; imageUrl?: string; raster?: boolean; resolution?: number };
export function LabMap({ goal, path, robot, places, onPick, disabled, anchors = [], calibrating, drawing = BUILTIN_DRAWING, imageUrl, raster = false, resolution }: Props) {
  const svg = useRef<SVGSVGElement>(null), stage = useRef<HTMLDivElement>(null);
  const drag = useRef<{ x: number; y: number; pan: Point; moved: boolean } | null>(null);
  const [zoom, setZoom] = useState(1), [pan, setPan] = useState<Point>({ x: 0, y: 0 }), [size, setSize] = useState({ width: 800, height: 420 });
  useEffect(() => {
    if (!stage.current) return;
    const observer = new ResizeObserver(([entry]) => {
      if (entry.contentRect.width > 0 && entry.contentRect.height > 0) setSize({ width: entry.contentRect.width, height: entry.contentRect.height });
    });
    observer.observe(stage.current); return () => observer.disconnect();
  }, []);
  useEffect(() => { setZoom(1); setPan({ x: 0, y: 0 }); }, [drawing.id, drawing.revision]);
  const viewWidth = (drawing.width * 1.1) / zoom, viewHeight = (drawing.height * 1.2) / zoom;
  const viewX = (drawing.width - viewWidth) / 2 - pan.x, viewY = (drawing.height - viewHeight) / 2 - pan.y;
  const scale = svgScreenScale({ width: viewWidth, height: viewHeight }, size);
  const unit = 1 / scale, labelSize = MAP_MARKERS.label * unit, robotSize = MAP_MARKERS.robot * unit;
  const reset = () => { setZoom(1); setPan({ x: 0, y: 0 }); };
  const pick = (clientX: number, clientY: number) => {
    const matrix = svg.current?.getScreenCTM();
    if (!matrix || disabled) return;
    const point = new DOMPoint(clientX, clientY).matrixTransform(matrix.inverse());
    onPick({ x: point.x, y: point.y });
  };
  return <div className="lab-map-workspace">
    <div className="lab-map-toolbar"><span title={drawing.name}><i className="lab-active-dot"/>{drawing.name}</span><div>
      <button type="button" aria-label="缩小平面图" onClick={() => setZoom(z => Math.max(.7, z / 1.25))}><Minus size={15}/></button>
      <span>{Math.round(zoom * 100)}%</span>
      <button type="button" aria-label="放大平面图" onClick={() => setZoom(z => Math.min(4, z * 1.25))}><Plus size={15}/></button>
      <button type="button" aria-label="适配平面图" onClick={reset}><Crosshair size={15}/></button>
    </div></div>
    <div className="lab-map-stage" ref={stage}>
      <svg ref={svg} viewBox={`${viewX} ${viewY} ${viewWidth} ${viewHeight}`} className={disabled ? "lab-floorplan locked" : "lab-floorplan"}
        role="img" aria-label={`${drawing.name}，点击选点，拖动平移`}
        onPointerDown={e => { e.currentTarget.setPointerCapture(e.pointerId); drag.current = { x: e.clientX, y: e.clientY, pan, moved: false }; }}
        onPointerMove={e => { const d = drag.current; if (!d) return; const dx = e.clientX - d.x, dy = e.clientY - d.y;
          if (Math.hypot(dx, dy) > 6) d.moved = true;
          if (d.moved) setPan({ x: d.pan.x + dx / scale, y: d.pan.y + dy / scale }); }}
        onPointerUp={e => { const d = drag.current; drag.current = null; if (d && !d.moved) pick(e.clientX, e.clientY); }}
        onPointerCancel={() => { drag.current = null; }} onLostPointerCapture={() => { drag.current = null; }}>
        {drawing.kind === "uploaded" ? imageUrl && <image className={raster ? "lab-raster-image" : undefined} style={{ imageRendering: raster ? "pixelated" : "auto" }} href={imageUrl} x={0} y={0} width={drawing.width} height={drawing.height}/> : <>
        <defs><pattern id="lab-floor-grid" width="36" height="36" patternUnits="userSpaceOnUse"><path d="M36 0 H0 V36" className="lab-grid-line"/></pattern></defs>
        <rect x="0" y="0" width={LAB.width} height={LAB.height} className="lab-floor-fill"/>
        <rect x="0" y="0" width={LAB.width} height={LAB.height} fill="url(#lab-floor-grid)"/>
        <rect x="944" y="24" width="234" height="496" rx="12" className="lab-corridor"/>
        <rect x="16" y="142" width="882" height="46" rx="9" className="lab-podium-fill"/>
        <rect x="16" y="375" width="882" height="46" rx="9" className="lab-bench-fill"/>
        <rect x="892" y="88" width="40" height="155" rx="8" className="lab-podium-fill"/>
        {LAB_BARRIERS.map(([a,b], i) => <line key={i} x1={a.x} y1={a.y} x2={b.x} y2={b.y} className={i < 5 ? "lab-wall-line" : "lab-obstacle-line"}/>)}
        <g className="lab-labels" style={{ fontSize: labelSize }}>
          <text x="440" y="132" textAnchor="middle">讲台</text>
          <text x="440" y="365" textAnchor="middle">实验台</text>
          <text x="1015" y="65" textAnchor="middle">老师处</text>
          <text x="1120" y="315" textAnchor="middle" className="lab-corridor-label">通道</text>
          <text x="1078" y="596" textAnchor="middle">门</text>
        </g>
        <path d="M1007 552 L1007 502" className="lab-door-leaf"/>
        <path d="M1007 502 Q1050 502 1057 552" className="lab-door-arc"/>
        </>}
        {path.length > 1 && <polyline points={path.map(p => `${p.x},${p.y}`).join(" ")} className="lab-planned-path"/>}
        {!calibrating && places.map((place,i) => <g key={place.id} transform={`translate(${place.drawing.x},${place.drawing.y})`}>
          <circle r={11 * unit} className="lab-place-ring"/>
          <text textAnchor="middle" dominantBaseline="central" className="lab-place-number" style={{ fontSize: labelSize }}>{i + 1}</text>
        </g>)}
        {goal && <g transform={`translate(${goal.x},${goal.y})`}><circle r={MAP_MARKERS.goal * unit} className="lab-goal-halo"/><circle r={MAP_MARKERS.goalDot * unit} className="lab-goal-dot"/></g>}
        {robot && <g className="lab-robot-marker" transform={`translate(${robot.x},${robot.y}) rotate(${robot.yaw * 180 / Math.PI})`}>
          <circle r={MAP_MARKERS.halo * unit} className="lab-robot-halo"/>
          <path d={`M${robotSize},0 L${-robotSize * .7},${-robotSize * .7} L${-robotSize * .35},0 L${-robotSize * .7},${robotSize * .7} Z`} className="lab-robot-body"/>
        </g>}
        {anchors.map((p,i) => <g key={i} transform={`translate(${p.x},${p.y})`}><circle r={MAP_MARKERS.anchor * unit} className="lab-anchor"/><text textAnchor="middle" dominantBaseline="central" style={{ fontSize: labelSize }}>{i + 1}</text></g>)}
      </svg>
    </div>
    <div className="lab-map-legend"><span><i className="lab-legend-obstacle"/>{raster ? `${drawing.width} × ${drawing.height} 格${resolution ? ` · ${(resolution * 100).toFixed(0)} cm/格` : ""} · 原始栅格` : drawing.kind === "uploaded" ? "参考图 · 通行性由 SLAM 判断" : "实验台／讲台 · 不可通行"}</span><span><i className="lab-legend-path"/>规划路径</span><span><i className="lab-legend-goal"/>目的地</span></div>
  </div>;
}
