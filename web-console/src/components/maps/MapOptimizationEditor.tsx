import { useEffect, useRef, useState } from 'react';
import { businessApi, createMapRequestId, type ManagedMap, type MapEdit, type MapPreview, type CleanupCandidate } from '../../services/businessApi';
import { navigate } from '../../lib/router';
import { Button } from '../ui';
import { MapDialog } from './MapManager';

type Point={x:number;y:number};
type Tool='brush'|'line'|'rectangle'|'pan'|'measure';
const tools:Record<Tool,string>={pan:'平移',brush:'画笔',line:'直线',rectangle:'矩形',measure:'测距'};

export function MapOptimizationEditor({map,originalUrl,onClose}:{map:ManagedMap;originalUrl:string;onClose:()=>void}) {
  const [operations,setOperations]=useState<MapEdit[]>([]),[redo,setRedo]=useState<MapEdit[]>([]);
  const [name,setName]=useState(`${map.name} · 优化版`.slice(0,128));
  const [tool,setTool]=useState<Tool>('pan'),[layer,setLayer]=useState<'map'|'keepout'>('map');
  const [value,setValue]=useState<-1|0|100>(-1),[width,setWidth]=useState(.10),[filled,setFilled]=useState(false);
  const [limit,setLimit]=useState(2),[candidates,setCandidates]=useState<CleanupCandidate[]>([]),[selected,setSelected]=useState<Set<string>>(new Set());
  const [preview,setPreview]=useState<(MapPreview&{signature:string})|null>(null);
  const [error,setError]=useState(''),[busy,setBusy]=useState(false),[previewing,setPreviewing]=useState(true),[analyzing,setAnalyzing]=useState(true);
  const [flags,setFlags]=useState({original:true,mask:true,diff:true,grid:false,invert:false,contrast:false});
  const [radius,setRadius]=useState(.25),[view,setView]=useState({x:0,y:0,w:map.width,h:map.height});
  const [draft,setDraft]=useState<Point[]>([]),[measurement,setMeasurement]=useState<Point[]>([]);
  const svg=useRef<SVGSVGElement>(null),gesture=useRef<{points:Point[];pan:boolean;client:Point;view:typeof view}|null>(null);
  const pointers=useRef(new Map<number,Point>()),pinch=useRef<{distance:number;view:typeof view}|null>(null),space=useRef(false);
  const requestId=useRef(createMapRequestId()),history=useRef({operations,redo,busy});history.current={operations,redo,busy};
  const signature=JSON.stringify(operations),resolution=map.resolution||.05,valid=preview?.signature===signature;
  function add(items:MapEdit[]){if(history.current.operations.length+items.length>100){setError('每个版本最多 100 步，请先保存当前版本');return;}setOperations([...history.current.operations,...items]);setRedo([]);setDraft([]);setError('');}
  function undo(){const h=history.current;if(!h.busy&&h.operations.length){setOperations(h.operations.slice(0,-1));setRedo([...h.redo,h.operations[h.operations.length-1]]);}}
  function redoStep(){const h=history.current;if(!h.busy&&h.redo.length){setOperations([...h.operations,h.redo[h.redo.length-1]]);setRedo(h.redo.slice(0,-1));}}
  function close(){if(!busy&&(!operations.length||window.confirm('有未保存的地图编辑，确定退出吗？')))onClose();}
  useEffect(()=>{
    function key(e:KeyboardEvent){if((e.target as HTMLElement).matches('input,textarea,select'))return;
      if(e.code==='Space'){space.current=true;e.preventDefault();}
      if((e.ctrlKey||e.metaKey)&&e.key.toLowerCase()==='z'){e.preventDefault();e.shiftKey?redoStep():undo();}
      if((e.ctrlKey||e.metaKey)&&e.key.toLowerCase()==='y'){e.preventDefault();redoStep();}}
    const up=()=>{space.current=false;},before=(e:BeforeUnloadEvent)=>{if(history.current.operations.length){e.preventDefault();e.returnValue='';}};
    window.addEventListener('keydown',key);window.addEventListener('keyup',up);window.addEventListener('blur',up);window.addEventListener('beforeunload',before);
    return()=>{window.removeEventListener('keydown',key);window.removeEventListener('keyup',up);window.removeEventListener('blur',up);window.removeEventListener('beforeunload',before);};
  },[]);
  useEffect(()=>{let active=true;setPreviewing(true);requestId.current=createMapRequestId();
    const timer=setTimeout(()=>{void businessApi.previewMapOptimization(map.id,{request_id:requestId.current,name:'预览',operations},radius)
      .then(v=>{if(active){setPreview({...v,signature});setError('');}}).catch(e=>{if(active)setError(e.message);}).finally(()=>{if(active)setPreviewing(false);});},250);
    return()=>{active=false;clearTimeout(timer);};},[signature,map.id,radius]);
  useEffect(()=>{let active=true;setAnalyzing(true);const timer=setTimeout(()=>{void businessApi.mapCleanupCandidates(map.id,operations,limit)
    .then(v=>{if(active){setCandidates(v.candidates);setSelected(new Set(v.candidates.map(c=>c.id)));}})
    .catch(e=>{if(active){setCandidates([]);setSelected(new Set());setError(e.message);}}).finally(()=>{if(active)setAnalyzing(false);});},450);
    return()=>{active=false;clearTimeout(timer);};},[signature,map.id,limit]);
  async function save(){if(!valid||previewing||busy||!name.trim()||!operations.length)return;setBusy(true);try{
    const result=await businessApi.deriveMap(map.id,{request_id:requestId.current,name:name.trim(),operations});setOperations([]);navigate(`/maps/${result.id}`);onClose();
  }catch(e){setError((e as Error).message);}finally{setBusy(false);}}
  function point(e:{clientX:number;clientY:number}):Point|null{const matrix=svg.current?.getScreenCTM();if(!matrix)return null;const p=new DOMPoint(e.clientX,e.clientY).matrixTransform(matrix.inverse());return{x:Math.max(0,Math.min(map.width-.001,p.x)),y:Math.max(0,Math.min(map.height-.001,p.y))};}
  function applyCandidates(target:-1|0){if(analyzing||busy)return;const points=candidates.filter(c=>selected.has(c.id)).flatMap(c=>c.cells.map(([x,y])=>({x,y})));const edits:MapEdit[]=[];
    for(let i=0;i<points.length;i+=20000)edits.push({type:'candidate',shape:'cells',points:points.slice(i,i+20000),value:target,max_cells:limit});if(edits.length)add(edits);}
  function toggleCandidate(id:string){setSelected(s=>{const next=new Set(s);next.has(id)?next.delete(id):next.add(id);return next;});}
  const measure=measurement.length===2?Math.hypot(measurement[1].x-measurement[0].x,measurement[1].y-measurement[0].y)*resolution:null;
  const brushWidth=Math.max(1,width/resolution),color=layer==='keepout'?'#e73e43':value===100?'#111':value===0?'#fff':'#9099a6';
  const filter=`${flags.invert?'invert(1) ':''}${flags.contrast?'contrast(1.6)':''}`;
  return <MapDialog title="编辑 SLAM 地图 · 另存版本" busy={busy} onClose={close}><div className="map-editor">
    <p className="map-help">原图保留，保存不会切换小车地图。红色为禁行区，浅红色为车体安全边界。自动建议不是椅子识别。</p>
    <div className="map-editor-toolbar">
      <label>编辑图层<select value={layer} disabled={busy} onChange={e=>setLayer(e.target.value as typeof layer)}><option value="map">地形栅格</option><option value="keepout">禁行遮罩</option></select></label>
      <label>绘制状态<select value={layer==='keepout'&&value===-1?100:value} disabled={busy} onChange={e=>setValue(Number(e.target.value) as typeof value)}><option value={100}>{layer==='keepout'?'添加禁行':'障碍物'}</option><option value={0}>{layer==='keepout'?'擦除禁行':'可通行（人工确认）'}</option>{layer==='map'&&<option value={-1}>未知区域</option>}</select></label>
      <label>工具<select value={tool} disabled={busy} onChange={e=>{setTool(e.target.value as Tool);setDraft([]);}}>{Object.entries(tools).map(([key,label])=><option key={key} value={key}>{label}</option>)}</select></label>
      <label>笔刷宽度（米）<input type="number" min={.01} max={2} step={.01} value={width} disabled={busy} onChange={e=>setWidth(Number(e.target.value))}/></label>
      <label><input type="checkbox" checked={filled} onChange={e=>setFilled(e.target.checked)}/>填充矩形</label>
      <Button disabled={busy||!operations.length} onClick={undo}>撤销</Button><Button disabled={busy||!redo.length} onClick={redoStep}>重做</Button>
      <Button onClick={()=>setView({x:0,y:0,w:map.width,h:map.height})}>适应窗口</Button><Button onClick={()=>setView(v=>({...v,w:Math.max(5,v.w*.8),h:Math.max(5,v.h*.8)}))}>放大</Button><Button onClick={()=>setView(v=>({...v,w:Math.min(map.width*16,v.w*1.25),h:Math.min(map.height*16,v.h*1.25)}))}>缩小</Button>
    </div>
    <div className="map-editor-options">{(Object.entries({original:'原图对照',mask:'禁行遮罩',diff:'修改高亮',grid:'米制网格',invert:'显示反色',contrast:'增强对比'}) as [keyof typeof flags,string][]).map(([key,label])=><label key={key}><input type="checkbox" checked={flags[key]} onChange={e=>setFlags({...flags,[key]:e.target.checked})}/>{label}</label>)}
      <label>车体半径（预览米）<input type="number" min={.01} max={2} step={.01} value={radius} onChange={e=>setRadius(Number(e.target.value))}/></label></div>
    <div className="map-editor-layout"><div className={`map-editor-canvases ${flags.original?'':'single'}`}>
      {flags.original&&<figure><figcaption>原始地形（同一缩放）</figcaption><svg viewBox={`${view.x} ${view.y} ${view.w} ${view.h}`}><image href={originalUrl} width={map.width} height={map.height} style={{filter}}/></svg></figure>}
      <figure><figcaption>{previewing?'正在生成预览…':`编辑预览 · ${valid?preview.changed_cells:0} 格 · ${valid?preview.changed_area_m2.toFixed(4):'0'} m²`}</figcaption>
      <svg ref={svg} className="map-editor-surface" viewBox={`${view.x} ${view.y} ${view.w} ${view.h}`} aria-label="地图编辑画布" onWheel={e=>{e.preventDefault();const p=point(e);if(!p)return;const factor=e.deltaY>0?1.15:1/1.15;setView(v=>{const f=Math.min(16*map.width,Math.max(5,v.w*factor))/v.w;return{x:p.x-(p.x-v.x)*f,y:p.y-(p.y-v.y)*f,w:v.w*f,h:v.h*f};});}}
        onPointerDown={e=>{if(busy||previewing)return;const p=point(e);if(!p)return;svg.current?.setPointerCapture(e.pointerId);pointers.current.set(e.pointerId,{x:e.clientX,y:e.clientY});
          if(pointers.current.size===2){const [a,b]=[...pointers.current.values()];pinch.current={distance:Math.hypot(a.x-b.x,a.y-b.y),view};gesture.current=null;setDraft([]);return;}
          gesture.current={points:[p],pan:tool==='pan'||space.current||e.button===1,client:{x:e.clientX,y:e.clientY},view};if(tool!=='pan')setDraft([p]);}}
        onPointerMove={e=>{if(!pointers.current.has(e.pointerId))return;pointers.current.set(e.pointerId,{x:e.clientX,y:e.clientY});
          if(pinch.current&&pointers.current.size===2){const [a,b]=[...pointers.current.values()],g=pinch.current;const f=g.distance/Math.max(1,Math.hypot(a.x-b.x,a.y-b.y));setView({...g.view,w:Math.min(map.width*16,Math.max(5,g.view.w*f)),h:Math.min(map.height*16,Math.max(5,g.view.h*f))});return;}
          const g=gesture.current;if(!g)return;if(g.pan){const box=svg.current!.getBoundingClientRect(),scale=Math.min(box.width/g.view.w,box.height/g.view.h);setView({...g.view,x:g.view.x-(e.clientX-g.client.x)/scale,y:g.view.y-(e.clientY-g.client.y)/scale});return;}
          const p=point(e);if(!p)return;if(tool==='brush'){const last=g.points[g.points.length-1];if(Math.hypot(p.x-last.x,p.y-last.y)>.25&&g.points.length<20000)g.points.push(p);}else g.points=[g.points[0],p];setDraft([...g.points]);}}
        onPointerCancel={e=>{pointers.current.delete(e.pointerId);gesture.current=null;pinch.current=null;setDraft([]);}}
        onPointerUp={e=>{pointers.current.delete(e.pointerId);if(pinch.current){if(!pointers.current.size)pinch.current=null;gesture.current=null;setDraft([]);return;}const g=gesture.current;gesture.current=null;setDraft([]);if(!g||g.pan)return;const end=point(e)||g.points[0];
          if(tool==='measure'){setMeasurement([g.points[0],end]);return;}if(tool==='brush'||tool==='line'||tool==='rectangle')add([{type:layer==='keepout'?'keepout':'paint',shape:tool,points:tool==='brush'?g.points:[g.points[0],end],value:layer==='keepout'&&value===-1?100:value,width_m:width,filled}]);}}>
        <defs><pattern id="editor-metric-grid" width={1/resolution} height={1/resolution} patternUnits="userSpaceOnUse"><path d={`M ${1/resolution} 0 L 0 0 0 ${1/resolution}`} fill="none" stroke="#6e92ad" strokeWidth={.5}/></pattern></defs>
        <image href={valid?preview.preview_url:originalUrl} width={map.width} height={map.height} style={{filter}}/>
        {valid&&flags.diff&&<image href={preview.diff_url} width={map.width} height={map.height}/>}
        {valid&&flags.mask&&preview.effective_keepout_url&&<image href={preview.effective_keepout_url} width={map.width} height={map.height}/>}
        {valid&&flags.mask&&preview.keepout_url&&<image href={preview.keepout_url} width={map.width} height={map.height}/>}
        {flags.grid&&<rect width={map.width} height={map.height} fill="url(#editor-metric-grid)" pointerEvents="none"/>}
        {!analyzing&&candidates.filter(c=>c.cells.some(([x,y])=>x>=view.x&&y>=view.y&&x<view.x+view.w&&y<view.y+view.h)).slice(0,800).map(c=><g key={c.id} pointerEvents={tool==='pan'?'auto':'none'} onPointerDown={e=>e.stopPropagation()} onClick={()=>toggleCandidate(c.id)}><title>疑似小孤立障碍 {c.id} · {c.area_m2.toFixed(4)} m²</title>{c.cells.map(([x,y])=><rect key={`${x},${y}`} x={x} y={y} width={1} height={1} fill={selected.has(c.id)?'#e9ab24':'#74859a'} stroke="#d08009" strokeWidth={.25}/>)}</g>)}
        {!!draft.length&&tool!=='rectangle'&&<polyline points={draft.map(p=>`${p.x},${p.y}`).join(' ')} fill="none" stroke={color} strokeWidth={brushWidth} strokeLinecap="round" opacity={.7} pointerEvents="none"/>}
        {draft.length===2&&tool==='rectangle'&&<rect x={Math.min(draft[0].x,draft[1].x)} y={Math.min(draft[0].y,draft[1].y)} width={Math.abs(draft[1].x-draft[0].x)} height={Math.abs(draft[1].y-draft[0].y)} fill={filled?color:'none'} stroke={color} strokeWidth={brushWidth} opacity={.7} pointerEvents="none"/>}
        {measurement.length===2&&<line x1={measurement[0].x} y1={measurement[0].y} x2={measurement[1].x} y2={measurement[1].y} stroke="#1675ce" strokeWidth={Math.max(.5,view.w/600)} pointerEvents="none"/>}
      </svg></figure></div>
      <aside className="map-editor-candidates"><h3>疑似小孤立障碍</h3><label>连通区域上限<select value={limit} disabled={busy} onChange={e=>setLimit(Number(e.target.value))}>{[1,2,3,4,6,8].map(n=><option key={n} value={n}>{n} 格 · {(n*resolution**2).toFixed(4)} m²</option>)}</select></label>
        <p role="status">{analyzing?'正在分析当前预览，请稍候…':`${candidates.length} 项建议，选中 ${selected.size} 项`}</p><div className="map-row-actions"><Button size="sm" disabled={analyzing||busy} onClick={()=>setSelected(new Set(candidates.map(c=>c.id)))}>全选</Button><Button size="sm" disabled={analyzing||busy} onClick={()=>setSelected(new Set())}>取消全选</Button></div>
        <div className="map-candidate-list">{candidates.slice(0,200).map(c=><label key={c.id}><input type="checkbox" checked={selected.has(c.id)} onChange={()=>toggleCandidate(c.id)}/><button type="button" className="map-candidate-focus" onClick={()=>{const [x,y]=c.cells[0];setView({x:x-30,y:y-30,w:60,h:60});}}>区域 {c.id} · {c.cells.length} 格</button></label>)}</div>
        {candidates.length>200&&<small>列表显示前 200 项；缩放地图可选择其他候选，全选覆盖全部候选。</small>}
        <Button disabled={busy||analyzing||!selected.size} onClick={()=>applyCandidates(-1)}>选中项改为未知</Button><Button disabled={busy||analyzing||!selected.size} onClick={()=>{if(window.confirm('请确认这些位置是可通行地面，而非固定障碍或未探测空间。确认清除为可通行？'))applyCandidates(0);}}>人工确认后清除为可通行</Button>
        <small>小点也可能是固定细柱。自动建议不会修改地图；未知区域不会被自动清成可通行。</small>
      </aside></div>
    <p className="map-help">空格拖动平移 · 滚轮/双指缩放 · Ctrl+Z 撤销 · Ctrl+Y 重做{measure!==null?` · 测量距离 ${measure.toFixed(3)} 米`:''}。半径仅用于预览；车端按实际配置生成安全边界。</p>
    <label>新版本名称<input maxLength={128} value={name} disabled={busy} onChange={e=>setName(e.target.value)}/></label>{error&&<p className="map-error" role="alert">{error}</p>}
    <div className="map-form-actions"><Button disabled={busy} onClick={close}>取消</Button><Button variant="primary" disabled={busy||previewing||!valid||!operations.length||!name.trim()} onClick={()=>void save()}>{busy?'正在保存…':'另存地图版本'}</Button></div>
  </div></MapDialog>;
}
