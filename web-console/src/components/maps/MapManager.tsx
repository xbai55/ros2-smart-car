import { useEffect, useRef, useState, type ReactNode } from "react";
import { ArrowLeft, Check, ImagePlus, MapPin, Pencil, Plus, RefreshCw, Trash2, X } from "lucide-react";
import { Link, navigate } from "../../lib/router";
import { useData } from "../../hooks/useData";
import { useBusinessSession } from "../../hooks/useBusinessSession";
import { businessApi, imagePoint, type ManagedMap, type MapPlace, type PlaceInput } from "../../services/businessApi";
import { Badge, Button, EmptyState, ErrorState, Panel } from "../ui";
import { DataTable, ObjectHeader, type Column } from "../shared";
import { LIVE_ROBOT_ID } from "../../liveControl";
import { MapOptimizationEditor } from "./MapOptimizationEditor";
import { RosMapImport } from './RosMapImport';

function canManage(session: ReturnType<typeof useBusinessSession>) {
  return !!session?.user.role?.permissions.some(permission => permission.name === "maps.manage");
}
function LoginNotice({ path }: { path: string }) {
  return <div className="page"><ObjectHeader title="地图管理" subtitle="上传地图图片，标注和管理常用地点"/><Panel><EmptyState title="登录后查看地图" hint="地图和地点保存在业务数据库中，请使用系统账户登录。"/><div className="map-center"><Link className="btn btn-primary" to={`/login?return=${encodeURIComponent(path)}`}>登录账户</Link></div></Panel></div>;
}
export function MapDialog({ title, children, onClose, busy = false }: { title: string; children: ReactNode; onClose: () => void; busy?: boolean }) {
  const ref = useRef<HTMLDialogElement>(null);
  useEffect(() => { ref.current?.showModal(); return () => { ref.current?.close(); }; }, []);
  return <dialog ref={ref} className="map-dialog" aria-label={title} onCancel={event => { event.preventDefault(); if (!busy) onClose(); }}>
    <div className="map-dialog-heading"><h2>{title}</h2><button type="button" className="map-icon-button" aria-label="关闭" disabled={busy} onClick={onClose}><X size={19}/></button></div>{children}
  </dialog>;
}
function dateLabel(map: ManagedMap) { return new Date(map.updated_at || map.created_at).toLocaleString("zh-CN", { hour12: false }); }
function resolutionLabel(map: ManagedMap) { return map.resolution ? Number(map.resolution.toPrecision(6)) : "—"; }

export function ManagedMapsPage() {
  const session = useBusinessSession();
  if (!session) return <LoginNotice path="/maps"/>;
  return <MapList key={session.user.id} manage={canManage(session)}/>;
}
function MapList({ manage }: { manage: boolean }) {
  const [importing,setImporting]=useState(false);
  const query = useData(businessApi.listMaps);
  const selection = useData(businessApi.getMapSelection);
  const [uploading, setUploading] = useState(false), [removing, setRemoving] = useState<ManagedMap | null>(null);
  const [name, setName] = useState(""), [floor, setFloor] = useState("1F"), [description, setDescription] = useState("");
  const [file, setFile] = useState<File | null>(null), [busy, setBusy] = useState(false), [error, setError] = useState("");
  const columns: Column<ManagedMap>[] = [
    { key: "name", header: "地图", render: map => <Link to={`/maps/${map.id}`} className="cell-strong"><strong>{map.name}</strong><em>{map.description || "点击查看与标注"}</em></Link> },
    { key: "floor", header: "楼层 / 区域", render: map => map.floor || "—" },
    { key: "size", header: "尺寸 / 来源", render: map => map.metadata.source === "slam" ? `SLAM · ${map.width} × ${map.height} 格 · ${resolutionLabel(map)} m/格` : map.image_url ? `${map.width} × ${map.height} px` : "尚未上传图片" },
    { key: "status", header: "状态", render: map => <Badge tone={map.active ? "success" : "neutral"}>{map.active ? "可用" : "已停用"}</Badge> },
    { key: "updated", header: "更新时间", render: dateLabel },
    { key: "actions", header: "操作", render: map => <div className="map-row-actions"><Link to={`/maps/${map.id}`} className="btn btn-outline btn-sm"><MapPin size={14}/>查看 / 标注</Link>{selection.data?.map_id===map.id&&<Badge tone="success">当前选用</Badge>}{manage&&map.active&&map.image_url&&<Button size="sm" disabled={busy} onClick={()=>void chooseMap(map)}>{selection.data?.map_id===map.id?"进入工作区":"选用地图"}</Button>}{manage && <Button size="sm" icon={Trash2} onClick={() => { setRemoving(map); setError(""); }}>删除</Button>}</div> },
  ];
  async function chooseMap(map: ManagedMap) {
    if (busy) return; setBusy(true); setError("");
    try { await businessApi.selectMap(map.id); navigate(`/robots/${LIVE_ROBOT_ID}/run`); }
    catch(e) { setError((e as Error).message); }
    finally { setBusy(false); }
  }
  async function submitUpload(event: React.FormEvent) {
    event.preventDefault(); if (!file || busy) return;
    setBusy(true); setError("");
    try { const result = await businessApi.uploadMap(file, name, floor, description); setUploading(false); navigate(`/maps/${result.id}`); }
    catch (e) { setError((e as Error).message); }
    finally { setBusy(false); }
  }
  async function remove() {
    if (!removing || busy) return;
    setBusy(true); setError("");
    try { await businessApi.deleteMap(removing.id); setRemoving(null); query.refetch(); }
    catch (e) { setError((e as Error).message); }
    finally { setBusy(false); }
  }
  return <div className="page">
    <ObjectHeader kicker="Maps" title="地图管理" subtitle="查看 SLAM 地图与上传平面图，选用地图并管理常用地点" badges={[{ label: `${query.data?.length || 0} 张地图`, tone: "blue" }, { label: query.error ? "服务未连接" : query.loading ? "正在读取数据库" : "数据库已接入", tone: query.error ? "danger" : query.loading ? "blue" : "success" }]} actions={<>{manage && <Button variant="primary" icon={ImagePlus} onClick={() => { setUploading(true); setName(""); setFloor("1F"); setDescription(""); setFile(null); setError(""); }}>添加地图</Button>}<Button icon={RefreshCw} onClick={()=>{query.refetch();selection.refetch();}} disabled={query.loading}>刷新</Button></>}/>
    {manage&&<div className="map-row-actions"><Button onClick={()=>setImporting(true)}>导入 ROS 地图</Button></div>}
    {importing&&<RosMapImport onClose={()=>{setImporting(false);query.refetch();}}/>}
    {error&&!removing&&!uploading&&<p className="map-error" role="alert">{error}</p>}
    {selection.error&&<p className="map-error" role="alert">无法读取当前选用地图：{selection.error}</p>}
    {manage&&selection.data?.map_id&&<p className="map-help">已选用地图保存在数据库中。<button className="btn btn-outline btn-sm" disabled={busy} onClick={()=>{setBusy(true);void businessApi.clearMapSelection().then(selection.refetch).catch(e=>setError(e.message)).finally(()=>setBusy(false));}}>取消选用</button></p>}
    {!manage && <p className="map-notice">当前账户可查看地图和地点，管理地图需要操作员或管理员权限。</p>}
    <Panel title="地图列表" className="list-panel" bodyClassName="panel-flush">{query.error ? <ErrorState title={query.error} onRetry={query.refetch}/> : <DataTable columns={columns} rows={query.data || []} rowKey={map => map.id} loading={query.loading} emptyTitle="暂无地图，可在建图页保存 SLAM 图，或添加平面图"/>}</Panel>
    <p className="map-help">SLAM 地图保留真实比例和原点，上传平面图需对齐后使用；选用后还需确认当前定位与地图一致。</p>
    {uploading && <MapDialog title="添加地图" onClose={() => setUploading(false)} busy={busy}><form onSubmit={submitUpload} className="map-form">
      <label>地图名称<input autoFocus required maxLength={128} value={name} onChange={event => setName(event.target.value)} placeholder="例如：综合实验室" disabled={busy}/></label>
      <label>楼层 / 区域<input maxLength={64} value={floor} onChange={event => setFloor(event.target.value)} placeholder="例如：一层" disabled={busy}/></label>
      <label>地图图片<input required type="file" accept="image/png,image/jpeg,image/webp" onChange={event => { const selected = event.target.files?.[0] || null; setFile(selected); if (!name && selected) setName(selected.name.replace(/\.[^.]+$/, "")); }} disabled={busy}/><small>支持 PNG、JPG、WebP，最大 10 MB。请选择实验室平面图或地图截图。</small></label>
      <label>备注<textarea maxLength={2000} value={description} onChange={event => setDescription(event.target.value)} placeholder="可填写地图来源、适用区域等" disabled={busy}/></label>
      {error && <p className="map-error" role="alert">{error}</p>}<div className="map-form-actions"><Button disabled={busy} onClick={() => setUploading(false)}>取消</Button><Button type="submit" variant="primary" disabled={busy || !file || !name.trim()}>{busy ? "正在上传…" : "上传并标注地点"}</Button></div>
    </form></MapDialog>}
    {removing && <MapDialog title="删除地图" onClose={() => setRemoving(null)} busy={busy}><p>删除“{removing.name}”及其图片和所有地点标注？</p><p className="map-help">已关联路线或任务的地图需要先解除关联。</p>{error && <p role="alert" className="map-error">{error}</p>}<div className="map-form-actions"><Button disabled={busy} onClick={() => setRemoving(null)}>取消</Button><Button variant="danger" disabled={busy} onClick={() => void remove()}>{busy ? "正在删除…" : "确认删除"}</Button></div></MapDialog>}
  </div>;
}

export function ManagedMapDetailPage({ id }: { id: string }) {
  const session = useBusinessSession();
  if (!session) return <LoginNotice path={`/maps/${id}`}/>;
  return <MapEditor key={`${id}:${session.user.id}`} id={id} manage={canManage(session)}/>;
}
type DraftPlace = PlaceInput & { id?: string };
function useMapImage(map: ManagedMap | null) {
  const [state, setState] = useState({ url: "", error: "", loading: false });
  useEffect(() => {
    let active = true, url = "";
    if (!map?.image_url) { setState({ url: "", error: "", loading: false }); return; }
    setState({ url: "", error: "", loading: true });
    businessApi.image(map.id).then(blob => {
      if (!active) return;
      url = URL.createObjectURL(blob); setState({ url, error: "", loading: false });
    }).catch(error => { if (active) setState({ url: "", error: error.message, loading: false }); });
    return () => { active = false; if (url) URL.revokeObjectURL(url); };
  }, [map?.id, map?.image_url]);
  return state;
}
function MapEditor({ id, manage }: { id: string; manage: boolean }) {
  const [optimizing, setOptimizing] = useState(false);
  const query = useData(() => businessApi.getMap(id), [id]);
  const places = useData(() => businessApi.listPlaces(id), [id]);
  const routes = useData(() => businessApi.listRoutes(id), [id]);
  const map = query.data, image = useMapImage(map);
  const selection = useData(businessApi.getMapSelection);
  const [marking, setMarking] = useState(false), [draft, setDraft] = useState<DraftPlace | null>(null);
  const [busy, setBusy] = useState(false), [error, setError] = useState(""), [message, setMessage] = useState("");
  const [removing, setRemoving] = useState<MapPlace | null>(null);
  const [properties, setProperties] = useState({ name: "", floor: "", description: "", active: true });
  const nameRef = useRef<HTMLInputElement>(null);
  const svgRef = useRef<SVGSVGElement>(null);
  useEffect(() => { if (map) setProperties({ name: map.name, floor: map.floor, description: map.description, active: map.active }); }, [map]);
  useEffect(() => { if (draft) nameRef.current?.focus(); }, [draft?.id, !!draft]);
  async function mutate(action: () => Promise<unknown>, success: string, then?: () => void) {
    if (busy) return;
    setBusy(true); setError(""); setMessage("");
    try { await action(); setMessage(success); query.refetch(); places.refetch(); selection.refetch(); then?.(); }
    catch (e) { setError((e as Error).message); }
    finally { setBusy(false); }
  }
  function pick(event: React.MouseEvent<SVGSVGElement>) {
    if (!map || !manage || !marking || busy || !image.url) return;
    const matrix = svgRef.current?.getScreenCTM(); if (!matrix) return;
    const coordinate = new DOMPoint(event.clientX, event.clientY).matrixTransform(matrix.inverse());
    const point = imagePoint(coordinate.x, coordinate.y, map.width, map.height);
    if (point) { setDraft(previous => ({ name: previous?.name || "", yaw: previous?.yaw || 0, ...(previous?.id ? { id: previous.id } : {}), ...point })); setError(""); setMessage(""); }
  }
  if (query.loading && !map) return <div className="page"><EmptyState title="正在读取地图…"/></div>;
  if (query.error || !map) return <div className="page"><Link to="/maps" className="back-link"><ArrowLeft size={15}/>返回地图列表</Link><ErrorState title={query.error || "地图不存在"} onRetry={query.refetch}/></div>;
  const markerSize = Math.max(map.width, map.height) / 70;
  function marker(place: Pick<MapPlace, "name" | "x" | "y">, index: number, selected = false, placeId?: string) {
    const select = () => { if (manage && !busy && placeId) { const place = places.data?.find(p => p.id === placeId); if (place) { setDraft({ ...place }); setMarking(true); setError(""); setMessage(""); } } };
    return <g key={placeId || "draft"} transform={`translate(${place.x} ${place.y})`} className={`map-place-marker${selected ? " selected" : ""}`} role={placeId && manage ? "button" : undefined} tabIndex={placeId && manage ? 0 : undefined} aria-label={`编辑地点 ${place.name}`} onClick={event => { event.stopPropagation(); select(); }} onKeyDown={event => { if (event.key === "Enter" || event.key === " ") { event.preventDefault(); select(); } }}>
      <circle r={markerSize * 1.1}/><text textAnchor="middle" dominantBaseline="central" fontSize={markerSize * 1.15}>{selected ? "+" : index + 1}</text>
      <text className="map-marker-label" x={place.x > map!.width * 0.72 ? -markerSize * 1.6 : markerSize * 1.6} textAnchor={place.x > map!.width * 0.72 ? "end" : "start"} dominantBaseline="central" fontSize={markerSize * 1.2}>{place.name || "新地点"}</text>
    </g>;
  }
  return <div className="page">
    <Link to="/maps" className="back-link"><ArrowLeft size={15}/>返回地图列表</Link>
    <ObjectHeader kicker="Map" title={map.name} subtitle={`${map.floor || "未设置区域"} · ${map.width} × ${map.height} ${map.metadata.source==="slam"?"格":"px"} · 更新于 ${dateLabel(map)}`} badges={[{ label: `${places.data?.length || 0} 个地点`, tone: "blue" }, { label: map.metadata.source==="slam"?`SLAM · ${resolutionLabel(map)} m/格`:"上传平面图", tone:"blue" }, { label: selection.data?.map_id===id?"当前选用":map.active ? "可用" : "已停用", tone: map.active ? "success" : "neutral" }]} actions={<>{manage&&<Button variant="primary" disabled={busy||!map.active||!image.url} onClick={()=>void mutate(()=>businessApi.selectMap(id),"地图已选用",()=>navigate(`/robots/${LIVE_ROBOT_ID}/run`))}>选用地图</Button>}<Button icon={RefreshCw} disabled={busy} onClick={() => { query.refetch(); places.refetch(); routes.refetch();selection.refetch(); }}>刷新</Button></>}/>
    {map.metadata.source==="slam"&&<p className="map-notice">这是带真实比例和坐标原点的 SLAM 栅格图。选用后会进入导航工作区；当前定位与地图坐标一致后才可规划。</p>}
    <p className="map-notice">{marking ? draft?.id ? "正在编辑地点：可点击地图调整位置，修改名称后保存。" : "标注模式：点击地图选位置，填写名称后保存。" : "地点标注保存在数据库中。平面图与实车定位地图对齐后，可用于导航目标。"}</p>
    {error && <p className="map-error" role="alert">{error}</p>}{message && <p className="map-success" role="status">{message}</p>}
    <div className="map-manager-layout">
      <Panel title="地图与地点" bodyClassName="panel-flush" action={manage && <Button size="sm" variant={marking ? "outline" : "primary"} icon={marking ? X : Plus} disabled={!image.url || busy} onClick={() => { setMarking(!marking); setDraft(null); setError(""); setMessage(""); }}>{marking ? "取消标注" : "标注地点"}</Button>}>
        <div className={`map-image-stage${marking ? " marking" : ""}`}>
          {image.loading ? <EmptyState title="正在加载地图图片…"/> : image.error ? <ErrorState title={image.error}/> : image.url ? <svg ref={svgRef} viewBox={`0 0 ${map.width} ${map.height}`} preserveAspectRatio="xMidYMid meet" onClick={pick} aria-label="地图图片及地点标注">
            <image href={image.url} width={map.width} height={map.height} style={map.metadata.source === "slam" ? { imageRendering: "pixelated" } : undefined}/>
            {(places.data || []).filter(place => place.id !== draft?.id).map((place, index) => marker(place, index, false, place.id))}
            {draft && marker(draft, 0, true)}
          </svg> : <EmptyState title="这张地图尚无图片" hint="可返回列表上传一张新的地图图片"/>}
        </div>
        <div className="map-image-footer"><span><MapPin size={14}/>{marking ? "点击图片选择地点位置" : manage ? "点击已有地点可编辑" : "查看已保存的地点标注"}</span><span>坐标单位：图片像素</span></div>
      </Panel>
      <aside className="map-manager-side">
        {manage && map.metadata.source === "slam" && <Panel title="地图优化"><p className="map-help">人工整理地形、处理小孤立障碍建议和禁行区域，保留原图并另存版本。</p><Button disabled={busy || !image.url} onClick={() => setOptimizing(true)}>预览与编辑</Button><Button disabled={busy} onClick={()=>void mutate(async()=>{const blob=await businessApi.exportRosMap(id),url=URL.createObjectURL(blob),link=document.createElement('a');link.href=url;link.download='ros-map.zip';link.click();setTimeout(()=>URL.revokeObjectURL(url),1000);},'地图、禁行遮罩和版本说明已导出')}>导出 ROS 地图包</Button>{typeof map.metadata.parent_map_id === "string" && <p><Link to={`/maps/${map.metadata.parent_map_id}`}>查看原图</Link></p>}</Panel>}
        {map.metadata.source==="slam"&&<Panel title="SLAM 地图文件"><p className="map-help">分辨率：{resolutionLabel(map)} 米/格；原点：{map.origin?.map(v=>v.toFixed(3)).join("，")}。</p><div className="map-row-actions">{(["yaml","pgm"] as const).map(kind=><Button key={kind} size="sm" disabled={busy} onClick={()=>void mutate(async()=>{const blob=await businessApi.mapFile(id,kind),url=URL.createObjectURL(blob),link=document.createElement("a");link.href=url;link.download=`map.${kind}`;link.click();setTimeout(()=>URL.revokeObjectURL(url),1000);},"地图文件已下载")}>下载 {kind.toUpperCase()}</Button>)}</div></Panel>}
        {draft && <Panel title={draft.id ? "编辑地点" : "新建地点"}><form className="map-form" onSubmit={event => { event.preventDefault(); if (draft.name.trim()) void mutate(() => businessApi.savePlace(id, { name: draft.name.trim(), x: draft.x, y: draft.y, yaw: draft.yaw }, draft.id), "地点已保存到数据库", () => { setDraft(null); setMarking(false); }); }}>
          <label>地点名称<input ref={nameRef} required maxLength={128} placeholder="例如：老师处、门口" value={draft.name} disabled={busy} onChange={event => setDraft({ ...draft, name: event.target.value })}/></label>
          <div className="map-coordinate-row"><label>X 坐标<input required type="number" step="any" min={0} max={map.width - 0.001} value={draft.x} disabled={busy} onChange={event => setDraft({ ...draft, x: Number(event.target.value) })}/></label><label>Y 坐标<input required type="number" step="any" min={0} max={map.height - 0.001} value={draft.y} disabled={busy} onChange={event => setDraft({ ...draft, y: Number(event.target.value) })}/></label></div>
          <label>到达朝向（度）<input type="number" min={-180} max={180} step={1} value={Math.round(draft.yaw * 180 / Math.PI)} disabled={busy} onChange={event => setDraft({ ...draft, yaw: Number(event.target.value) * Math.PI / 180 })}/></label><small>图片向右为 0°，向下为 90°。可直接点击地图调整位置。</small><Button type="submit" variant="primary" icon={Check} disabled={busy || !draft.name.trim()}>{busy ? "正在保存…" : "保存地点"}</Button>
        </form></Panel>}
        <Panel title="地点列表" action={<Badge tone="blue">{places.data?.length || 0}</Badge>}>
          {places.error ? <ErrorState title={places.error} onRetry={places.refetch}/> : places.loading ? <EmptyState title="正在读取地点…"/> : places.data?.length ? <ul className="map-place-list">{places.data.map((place, index) => <li key={place.id}><span className="map-place-index">{index + 1}</span><div><strong>{place.name}</strong><small>{place.x.toFixed(1)}, {place.y.toFixed(1)} px</small></div>{manage && <><button className="map-icon-button" aria-label={`编辑${place.name}`} disabled={busy} onClick={() => { setDraft({ ...place }); setMarking(true); setError(""); setMessage(""); }}><Pencil size={15}/></button><button className="map-icon-button danger" aria-label={`删除${place.name}`} disabled={busy} onClick={() => { setRemoving(place); setError(""); }}><Trash2 size={15}/></button></>}</li>)}</ul> : <EmptyState title="尚未标注地点" hint={manage ? "点击“标注地点”，再点击地图选位置" : "管理员标注后会显示在这里"}/>}
        </Panel>
        <Panel title="地图属性"><form className="map-form" onSubmit={event => { event.preventDefault(); void mutate(() => businessApi.updateMap(id, properties), "地图属性已保存"); }}>
          <label>地图名称<input required maxLength={128} value={properties.name} disabled={!manage || busy} onChange={event => setProperties({ ...properties, name: event.target.value })}/></label>
          <label>楼层 / 区域<input maxLength={64} value={properties.floor} disabled={!manage || busy} onChange={event => setProperties({ ...properties, floor: event.target.value })}/></label>
          <label>备注<textarea maxLength={2000} value={properties.description} disabled={!manage || busy} onChange={event => setProperties({ ...properties, description: event.target.value })}/></label>
          <label className="map-checkbox"><input type="checkbox" checked={properties.active} disabled={!manage || busy} onChange={event => setProperties({ ...properties, active: event.target.checked })}/>启用这张地图</label>
          {manage && <Button type="submit" disabled={busy || !properties.name.trim()}>保存属性</Button>}
        </form></Panel>
        <Panel title="关联路线">{routes.error ? <p className="map-help">{routes.error}</p> : routes.data?.length ? routes.data.map(route => <div key={route.id} className="map-associated-route"><strong>{route.name}</strong><small>{(route.waypoints.length || route.points.length)} 个航点</small></div>) : <EmptyState title="暂无关联路线"/>}</Panel>
      </aside>
    </div>
    {optimizing && <MapOptimizationEditor map={map} originalUrl={image.url} onClose={() => setOptimizing(false)}/>}
    {removing && <MapDialog title="删除地点" busy={busy} onClose={() => setRemoving(null)}><p>删除地点“{removing.name}”？</p>{error && <p className="map-error" role="alert">{error}</p>}<div className="map-form-actions"><Button disabled={busy} onClick={() => setRemoving(null)}>取消</Button><Button variant="danger" disabled={busy} onClick={() => void mutate(() => businessApi.deletePlace(id, removing.id), "地点已删除", () => { if (draft?.id === removing.id) { setDraft(null); setMarking(false); } setRemoving(null); })}>确认删除</Button></div></MapDialog>}
  </div>;
}
