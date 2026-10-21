import { useEffect, useRef, useState } from "react";
import { ArrowRight, CheckCircle2, MapPin, Navigation, Plus, RefreshCw, Settings2, Square, Trash2, Undo2 } from "lucide-react";
import { useRobotStream } from "../../hooks/useRobotStream";
import { useNavigationDrawing } from "../../hooks/useNavigationDrawing";
import { BUILTIN_DRAWING, DEFAULT_PLACES, drawingToWorld, drawingYawToWorld, mapKey, sameDrawing, validDrawingPoint, validImagePoint, worldToDrawing, worldYawToDrawing, type CalibrationPair, type NavigationConfig, type NavigationPlan, type Place, type Point } from "../../labNavigation";
import { LabMap } from "./LabMap";
import { LiveMapCanvas } from "./LiveMapCanvas";
import { Link } from "../../lib/router";
import { savedSlamAnchors } from "../../slamMapSelection";
import { SlamNavigationWorkspace } from "./SlamNavigationWorkspace";
import { calibrationPreview } from "../../calibrationPreview";
import { NavigationSetup, NavigationTaskPanel } from "./NavigationOperations";

export function NavigationWorkspace() {
  const [mode, setMode] = useState<"slam" | "fusion">("slam");
  const [locked, setLocked] = useState(false);
  return <div className="navigation-modes"><div className="navigation-mode-tabs" role="group" aria-label="导航方式">
    <button type="button" disabled={locked} aria-pressed={mode === "slam"} onClick={() => setMode("slam")}>SLAM 直接导航</button>
    <button type="button" disabled={locked} aria-pressed={mode === "fusion"} onClick={() => setMode("fusion")}>平面图融合 · 进阶</button>
  </div>{mode === "slam" ? <SlamNavigationWorkspace onActive={setLocked}/> : <FusionNavigationWorkspace onActive={setLocked}/>}</div>;
}

function FusionNavigationWorkspace({ onActive }: { onActive: (active: boolean) => void }) {
  const { api, mapSnapshot: map, status, connection } = useRobotStream();
  const [config, setConfig] = useState<NavigationConfig>({ calibration: null, places: DEFAULT_PLACES });
  const source = useNavigationDrawing(config.calibration), { drawing, imageUrl } = source;
  const isRaster = source.selected?.metadata.source === "slam";
  const [tasksExpanded, setTasksExpanded] = useState(false);
  const [target, setTarget] = useState<Place | null>(null), [plan, setPlan] = useState<NavigationPlan | null>(null);
  const [error, setError] = useState(""), [busy, setBusy] = useState(false), [name, setName] = useState("");
  const [align, setAlign] = useState(false), [pairs, setPairs] = useState<CalibrationPair[]>([]), [anchor, setAnchor] = useState<Point | null>(null);
  const [editingPair, setEditingPair] = useState<number | null>(null);
  const diagnostics = calibrationPreview(pairs, drawing);
  const [alignmentKey, setAlignmentKey] = useState(""), [view, setView] = useState<"live" | "drawing">("live");
  const generation = useRef(0), mounted = useRef(true);
  const autoAttempt = useRef("");
  const [taskActive, setTaskActive] = useState(false), [locating, setLocating] = useState(false), [initialPoint, setInitialPoint] = useState<Point | null>(null);
  const key = map ? mapKey(map) : "", calibration = config.calibration;
  useEffect(() => { setInitialPoint(null); setLocating(false); }, [key]);
  const sourceMatches = sameDrawing(calibration?.drawing, drawing);
  const sourceReady = !source.error && !source.loading && (drawing.kind === "builtin" || !!imageUrl);
  const aligned = !!calibration && !calibration.invalidated && calibration.map_key === key && !!map && sourceMatches && sourceReady;
  const online = connection === "connected", nav = status.navigation;
  const active = nav.state === "starting" || nav.state === "running", locked = active || taskActive, canPlan = aligned && online && nav.ready && !locked;
  useEffect(() => { onActive(locked); }, [locked, onActive]);
  const ownPlaces = sourceMatches ? config.places : drawing.kind === "builtin" ? DEFAULT_PLACES : [];
  const places = [...ownPlaces, ...source.places];
  useEffect(() => { mounted.current = true; return () => { mounted.current = false; generation.current++; }; }, []);
  useEffect(() => {
    if (!online) return;
    let stopped = false, timer: ReturnType<typeof setTimeout> | undefined;
    const load = async () => {
      try { const value = await api.getNavigationConfig(); if (!stopped) setConfig(previous => JSON.stringify(previous) === JSON.stringify(value) ? previous : value); }
      catch { if (!stopped) setError("车端尚未提供导航配置，请更新小车端服务"); }
      if (!stopped) timer = setTimeout(() => void load(), 3000);
    };
    void load();
    return () => { stopped = true; if (timer) clearTimeout(timer); };
  }, [api, online]);
  useEffect(() => { generation.current++; setPlan(null); setBusy(false); }, [key, calibration, online]);
  useEffect(() => { generation.current++; setTarget(null); setPlan(null); setPairs([]); setAnchor(null); setEditingPair(null); setAlign(false); setError(""); setView(isRaster ? "live" : drawing.kind==="uploaded"?"drawing":"live"); }, [drawing.id, drawing.revision, drawing.kind, isRaster]);
  useEffect(()=>{
    const anchors=savedSlamAnchors(source.selected,map);
    const attempt=`${drawing.id}:${key}:${map?.session_id}`;
    if (!online || locked || busy || aligned || !sourceReady || !anchors || autoAttempt.current===attempt) return;
    autoAttempt.current=attempt;
    const request=++generation.current;setBusy(true);setError("");
    void api.calibrateNavigation(anchors,key,drawing).then(value=>{
      if (mounted.current&&request===generation.current) {setConfig(value);setView("live");}
    }).catch(e=>{if(mounted.current&&request===generation.current)setError(e.message);})
      .finally(()=>{if(mounted.current&&request===generation.current)setBusy(false);});
  },[api,source.selected,map,drawing,key,online,active,busy,aligned,sourceReady]);
  const robot = aligned && online && status.map_pose.ok ? { ...worldToDrawing(status.map_pose, calibration!.matrix), yaw: worldYawToDrawing(status.map_pose.yaw, calibration!.matrix) } : null;
  const worldPath = aligned ? active ? nav.path : plan && plan.map_key === key ? plan.path : [] : [];
  const worldGoal = aligned ? active ? nav.goal : target ? drawingToWorld(target.drawing, calibration!.matrix) : null : null;
  const choose = (place: Place) => { generation.current++; setPlan(null); setBusy(false); setError(""); setTarget(place); };
  const pick = (p: Point) => {
    if (locked || busy) return;
    if (!(drawing.kind === "builtin" ? validDrawingPoint(p) : validImagePoint(p, drawing))) { setError("请选择图内位置；目标是否可通行将由实车地图检查"); return; }
    choose({ id: "custom", name: "自选位置", drawing: p, yaw: robot?.yaw ?? -Math.PI / 2 });
  };
  async function preview() {
    if (!target || !canPlan || busy) return;
    const request = ++generation.current; setBusy(true); setError(""); setPlan(null);
    try {
      const result = await api.planNavigation({ ...drawingToWorld(target.drawing, calibration!.matrix), yaw: drawingYawToWorld(target.yaw, calibration!.matrix) }, key, calibration!.matrix, drawing);
      if (mounted.current && request === generation.current) setPlan(result);
    } catch (e) { if (mounted.current && request === generation.current) setError((e as Error).message); }
    finally { if (mounted.current && request === generation.current) setBusy(false); }
  }
  async function mutate(action: () => Promise<unknown>) {
    setBusy(true); setError("");
    try { await action(); } catch (e) { if (mounted.current) setError((e as Error).message); }
    finally { if (mounted.current) setBusy(false); }
  }
  const reason = !online ? "连接小车后可导航" : !sourceReady ? "正在等待地图，请检查图片加载状态" : !aligned ? source.selected?.metadata.source==="slam"?"正在核对 SLAM 坐标；不同建图会话需重新定位或对齐后使用":"请选择四组对应点，将平面图与 SLAM 地图对齐" : !nav.ready ? nav.message : "在地图上选点，先预览路线，再开始导航";
  const drawingProps = { drawing, imageUrl, places, disabled: locked || busy, raster: isRaster, resolution: source.selected?.resolution };
  return <div className="navigation-workspace">
    <NavigationSetup api={api} maps={source.maps} online={online} locked={locked} locating={locating} setLocating={value => { setLocating(value); if (value) { setAlign(false); setView("live"); } }} initialPoint={initialPoint}/>
    <div className="navigation-heading"><div><strong>地图与导航</strong><span>{active ? nav.message : reason}</span></div><button className="btn btn-outline" disabled={!online || !map || locked || busy || !sourceReady} onClick={() => { setAlign(!align); setPairs([]); setAnchor(null); setEditingPair(null); setAlignmentKey(key); setPlan(null); generation.current++; }}><Settings2 size={14}/>{align ? "返回地图" : "地图对齐"}</button></div>
    <div className="drawing-source"><label>选用地图<select aria-label="参考平面图" value={drawing.id} disabled={locked || busy || source.loading} onChange={e => source.choose(e.target.value)}><option value={BUILTIN_DRAWING.id}>内置实验室平面图</option>{source.maps.map(m => <option key={m.id} value={m.id}>{m.name} · {m.metadata.source==="slam"?"SLAM · ":""}{m.width} × {m.height}</option>)}</select></label><button className="btn btn-outline" aria-label="刷新上传地图" disabled={locked || busy || source.loading} onClick={()=>{autoAttempt.current="";source.refresh();}}><RefreshCw size={14}/></button><Link to="/maps" className="drawing-manage">地图管理</Link>
      <small>{source.loading ? "正在读取地图与标注…" : !source.loggedIn ? "登录后可选择已保存地图" : source.selected?.metadata.source==="slam"?"保留 SLAM 真实比例；选用不等于已完成定位":"图片坐标经标定转换为米制坐标"}</small></div>
    {source.error && <div className="navigation-error" role="alert">{source.error}</div>}
    {source.placesError && <div className="navigation-map-note" role="status">{source.placesError}</div>}
    {align ? <div className="navigation-alignment">
      <div className="alignment-progress" aria-label={`已配对 ${pairs.length} 组，共四组`}>{[0, 1, 2, 3].map(i => <span key={i} className={i < pairs.length ? "done" : i === pairs.length ? "current" : ""}>{i < pairs.length ? <CheckCircle2 size={16}/> : i + 1}<span>对应点 {i + 1}</span></span>)}</div>
      <p>选择四个分散、易辨认的墙角或固定物体端点。每组先点左侧平面图，再点右侧 SLAM 地图中的同一位置。图纸应尽量按实际比例绘制。</p>
      <strong>{pairs.length === 4 ? "四组位置已选好，可以保存" : anchor ? `第 ${pairs.length + 1} 组：请点击 SLAM 地图中的对应位置` : `第 ${pairs.length + 1} 组：请先点击平面图`}</strong>
      <div className="navigation-align-maps"><LabMap {...drawingProps} places={[]} goal={anchor} path={[]} robot={null} anchors={pairs.map(p => p.drawing)} calibrating disabled={!!anchor || pairs.length === 4 && editingPair === null || busy} onPick={p => { if (p.x >= 0 && p.y >= 0 && p.x <= drawing.width && p.y <= drawing.height) setAnchor(p); }}/>
        <LiveMapCanvas anchors={pairs.map(p => p.world)} onPick={p => { if (anchor && (pairs.length < 4 || editingPair !== null) && !busy) { const pair = { drawing: anchor, world: p }; setPairs(previous => editingPair === null ? [...previous, pair] : previous.map((old, i) => i === editingPair ? pair : old)); setAnchor(null); setEditingPair(null); } }}/></div>
      <div className="navigation-align-actions"><span>{editingPair !== null ? `正在重选第 ${editingPair + 1} 组：先选左图，再选右图` : `已配对 ${pairs.length} / 4 · 优先选分散的实体墙角`}</span><button className="btn btn-outline" disabled={busy || !anchor && !pairs.length} onClick={() => { if (anchor) setAnchor(null); else if (editingPair !== null) setEditingPair(null); else setPairs(p => p.slice(0, -1)); }}><Undo2 size={14}/>撤销上一步</button><button className="btn btn-outline" disabled={busy} onClick={() => { setPairs([]); setAnchor(null); setEditingPair(null); setAlignmentKey(key); }}>重新选择</button><button className="btn btn-primary" disabled={pairs.length !== 4 || !!anchor || editingPair !== null || busy || key !== alignmentKey} onClick={() => void mutate(async () => { const result = await api.calibrateNavigation(pairs, key, drawing); if (!sameDrawing(result.calibration?.drawing, drawing)) throw new Error("车端不支持上传地图标定，请更新车端服务"); setConfig(result); setAlign(false); setView("live"); })}>保存对齐</button></div>
      <div className="alignment-pair-list">{pairs.map((_, i) => <button key={i} type="button" className="btn btn-outline" aria-pressed={editingPair === i} disabled={busy} onClick={() => { setEditingPair(i); setAnchor(null); }}>重选第 {i + 1} 组{diagnostics?.errors ? ` · ${(diagnostics.errors[i] * 100).toFixed(1)} cm` : ""}</button>)}</div>
      {diagnostics && <div className={`alignment-diagnostics${diagnostics.maxError === null || diagnostics.maxError > .1 ? " warning" : ""}`} role="status">
        <strong>{diagnostics.maxError === null ? "点位接近共线，无法稳定拟合" : `拟合最大偏差 ${(diagnostics.maxError * 100).toFixed(1)} cm · 保存门槛 10 cm`}</strong>
        <p>{diagnostics.concentrated ? "点位在某个方向过于集中。请尽量选房间四周的墙角，避免只选同一条走廊两端的门口。" : "两边必须选同一实体位置，例如墙面交点；不要用门扇弧线、阴影边缘或模糊噪点配对。"}</p>
        <p>逐点数值是四点共同拟合后的残差，不能据此断定某一个点选错。图纸若为示意图或 SLAM 已变形，需修正图纸或重建地图；通过标定也不等于定位准确。最终以车端校验为准。</p>
      </div>}
      {key !== alignmentKey && <p role="alert">SLAM 地图范围已变化，请重新选择对应位置。建议完成建图后再标定。</p>}
    </div> : <div className="navigation-layout">
      <div className="navigation-map"><div className="map-view-tabs"><button aria-pressed={view === "live"} onClick={() => setView("live")}>{isRaster ? "SLAM 实时地图" : "SLAM 融合视图"}</button><button aria-pressed={view === "drawing"} onClick={() => setView("drawing")}>{isRaster ? "已保存地图" : "平面图视图"}</button><span className={aligned ? "alignment-state ready" : "alignment-state"}>{aligned ? "已对齐" : "未对齐"}</span></div>
        {view === "live" ? <LiveMapCanvas overlay={aligned && drawing.kind === "uploaded" ? { imageUrl, width: drawing.width, height: drawing.height, matrix: calibration!.matrix, name: drawing.name, raster: isRaster } : undefined} path={worldPath} goal={initialPoint && !locked ? initialPoint : worldGoal} places={aligned ? places.map(p => ({ ...drawingToWorld(p.drawing, calibration!.matrix), name: p.name })) : []} onPick={p => { if (locating && !locked) { setInitialPoint(p); setLocating(false); } else if (aligned) pick(worldToDrawing(p, calibration!.matrix)); else setError("请先点击“地图对齐”，标定当前平面图后再选导航目标"); }}/>
          : <LabMap {...drawingProps} goal={active && aligned && nav.goal ? worldToDrawing(nav.goal, calibration!.matrix) : target?.drawing || null} path={aligned ? worldPath.map(p => worldToDrawing(p, calibration!.matrix)) : []} robot={robot} onPick={pick}/>}
        <div className="navigation-map-note">{aligned ? `参考图：${drawing.name} · ${calibration?.max_error == null ? "" : `标定点最大误差 ${(calibration.max_error * 100).toFixed(1)} cm · `}路线由车端规划` : "SLAM 显示真实环境；参考图未对齐时不会叠加，也不能启动导航"}</div>
        {aligned && calibration?.errors && <details className="alignment-quality"><summary>查看标定误差</summary><p>{calibration.errors.map((e, i) => `点 ${i + 1}：${(e * 100).toFixed(1)} cm`).join(" · ")}</p><p>这是选点拟合误差，不能代表整张图的定位精度。重新建图或图纸更换后需检查并重新标定。</p></details>}
      </div>
      <aside className="navigation-panel">
        <div className="navigation-panel-title"><MapPin size={17}/><strong>选择目的地</strong></div>
        <div className="navigation-places">{places.length === 0 && <p className="navigation-hint">此地图暂无地点，可在地图上选点，或在地图管理中标注。</p>}{places.map((place, i) => <div key={place.id}><button className={target?.id === place.id ? "navigation-place selected" : "navigation-place"} disabled={locked || busy} onClick={() => choose(place)}><span>{i + 1}</span>{place.name}<ArrowRight size={14}/></button>{!place.id.startsWith("business:") && place.id !== "teacher" && place.id !== "door" && <button className="navigation-delete" aria-label={`删除${place.name}`} disabled={!online || busy || active || !aligned} onClick={() => void mutate(async () => { setConfig(await api.removeNavigationPlace(place.id)); if (target?.id === place.id) setTarget(null); setPlan(null); })}><Trash2 size={13}/></button>}</div>)}</div>
        <div className="navigation-target"><span>当前目的地</span><strong>{active ? "正在执行导航" : target?.name || "点击地图中的位置"}</strong><small>障碍与未知区域由车端检查，图片上的空白不代表可通行</small></div>
        {target && !locked && <label className="navigation-yaw">到达朝向（图片角度）<input aria-label="导航到达朝向" type="number" min={-180} max={180} value={Math.round(target.yaw * 180 / Math.PI)} onChange={e => choose({ ...target, yaw: Number(e.target.value) * Math.PI / 180 })}/><small>向右 0°，向下 90°</small></label>}
        {plan && !active && <div className="navigation-distance"><span>路线长度</span><strong>{plan.distance.toFixed(2)} m</strong></div>}{active && <div className="navigation-distance"><span>剩余距离</span><strong>{nav.distance_remaining == null ? "—" : `${nav.distance_remaining.toFixed(2)} m`}</strong></div>}
        <button className="btn btn-outline navigation-action" disabled={!target || !canPlan || busy} onClick={() => void preview()}>{busy ? "正在处理…" : plan ? "重新预览路线" : "预览路线"}</button>
        <button className="btn btn-primary navigation-action" disabled={!plan || !canPlan || busy || plan.map_key !== key} onClick={() => void mutate(async () => { window.dispatchEvent(new Event("robot-control-stop")); await api.startNavigation(plan!.plan_id); setPlan(null); })}><Navigation size={15}/>开始导航</button>
        <button className="btn btn-outline navigation-action navigation-stop" disabled={!online || !active && !busy} onClick={() => { generation.current++; void mutate(async () => { await api.cancelNavigation(); setPlan(null); }); }}><Square size={14}/>停止导航</button>
        <p className="navigation-hint">{active || ["succeeded", "canceled", "failed"].includes(nav.state) ? nav.message : reason}</p>
        <details className="navigation-save"><summary><Plus size={14}/>保存为导航地点</summary><label htmlFor="navigation-place-name">地点名称</label><input id="navigation-place-name" maxLength={40} value={name} placeholder="例如：实验台旁" onChange={e => setName(e.target.value)}/><button className="btn btn-outline" disabled={!target || !aligned || !online || !name.trim() || busy || locked} onClick={() => void mutate(async () => { setConfig(await api.addNavigationPlace(name.trim(), target!.drawing, target!.yaw, { map_key: key, calibration_matrix: calibration!.matrix, calibration_drawing: drawing })); setName(""); })}>保存当前点</button></details>
      </aside>
    </div>}
    {!align && <details className="navigation-task-disclosure" open={tasksExpanded || taskActive} onToggle={e => setTasksExpanded(e.currentTarget.open)}><summary>文件运输与多点巡航<span>{taskActive ? "任务执行中" : "展开配置任务"}</span></summary><NavigationTaskPanel api={api} online={online} aligned={aligned && nav.ready} calibration={calibration} drawing={drawing} mapKey={key} target={target} mapId={source.selected?.id} controlSessionId={map?.session_id} onActive={setTaskActive}/></details>}
    {error && <div className="navigation-error" role="alert">{error}</div>}
  </div>;
}
