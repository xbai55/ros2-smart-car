import { useEffect, useRef, useState } from "react";
import { MapPin, Navigation, Plus, RefreshCw, Square, Trash2 } from "lucide-react";
import { useRobotStream } from "../../hooks/useRobotStream";
import { useBusinessSession } from "../../hooks/useBusinessSession";
import { businessApi, createMapRequestId, type ManagedMap } from "../../services/businessApi";
import { directPointError, directSlamRegistration, matchesDirectRegistration } from "../../directSlamNavigation";
import { BUILTIN_DRAWING, drawingToWorld, drawingYawToWorld, mapKey, worldToDrawing, worldYawToDrawing, type Calibration, type Place, type Point, type NavigationPlan } from "../../labNavigation";
import { LiveMapCanvas } from "./LiveMapCanvas";
import { NavigationSetup, NavigationTaskPanel } from "./NavigationOperations";
import { Link } from "../../lib/router";

export function SlamNavigationWorkspace({ onActive }: { onActive: (active: boolean) => void }) {
  const live=useRobotStream(), {api,status,mapSnapshot:map,mapStale}=live;
  const session=useBusinessSession();
  const manage=!!session?.user.role?.permissions.some(p=>p.name==="maps.manage");
  const [maps,setMaps]=useState<ManagedMap[]>([]),[selectedId,setSelectedId]=useState("");
  const [catalogError,setCatalogError]=useState(""),[placesError,setPlacesError]=useState("");
  const [reload,setReload]=useState(0),[catalogLoading,setCatalogLoading]=useState(false);
  const [calibration,setCalibration]=useState<Calibration|null>(null),[registering,setRegistering]=useState(false);
  const [target,setTarget]=useState<Place|null>(null),[places,setPlaces]=useState<Place[]>([]),[plan,setPlan]=useState<NavigationPlan|null>(null);
  const [busy,setBusy]=useState(false),[error,setError]=useState(""),[name,setName]=useState(""),[mapName,setMapName]=useState("");
  const [locating,setLocating]=useState(false),[initialPoint,setInitialPoint]=useState<Point|null>(null);
  const [tasksExpanded,setTasksExpanded]=useState(false),[taskActive,setTaskActive]=useState(false);
  const mounted=useRef(true),generation=useRef(0),attempt=useRef(""),saveId=useRef(createMapRequestId());
  const selectionTouched=useRef(false),selectionStorage=`insightrover:slam-direct:${session?.user.id||"guest"}`;
  const rememberMap=(id:string)=>{selectionTouched.current=true;try{localStorage.setItem(selectionStorage,id||"@current");}catch{/* Storage may be disabled; map data still lives in the backend. */}};
  const selected=maps.find(m=>m.id===selectedId),key=map?mapKey(map):"";
  // An unavailable selected asset must not silently fall back to another map.
  const expected=selectedId&&!selected?null:directSlamRegistration(selected,map);
  const registered=matchesDirectRegistration(calibration,expected);
  const online=live.connection==="connected",nav=status.navigation;
  const active=nav.state==="starting"||nav.state==="running",locked=active||taskActive;
  const mapConfirmed=registered&&online&&!mapStale;
  const usable=mapConfirmed&&status.map_pose.ok;
  const canPlan=usable&&nav.ready&&!locked&&!busy&&!registering;
  const context=`${key}:${selectedId}`;
  useEffect(()=>{onActive(locked);},[locked,onActive]);
  useEffect(()=>{mounted.current=true;return()=>{mounted.current=false;generation.current++;};},[]);
  useEffect(()=>{generation.current++;attempt.current="";setTarget(null);setPlan(null);setInitialPoint(null);setLocating(false);setError("");},[context]);

  useEffect(()=>{
    let alive=true;
    if(!session){setMaps([]);setCatalogError("");return;}
    setCatalogLoading(true);setCatalogError("");
    void Promise.all([businessApi.listMaps(),businessApi.getMapSelection()]).then(([items,selection])=>{
      if(!alive)return;
      const grids=items.filter(m=>m.active&&m.metadata.source==="slam");setMaps(grids);
      setSelectedId(previous=>{
        if(previous||selectionTouched.current)return previous;
        let remembered:string|null=null;try{remembered=localStorage.getItem(selectionStorage);}catch{/* Keep the session usable without local storage. */}
        if(remembered==="@current")return "";
        return grids.find(m=>m.id===remembered)?.id||grids.find(m=>m.id===selection.map_id)?.id||"";
      });
    }).catch(e=>{if(alive)setCatalogError(e.message);}).finally(()=>{if(alive)setCatalogLoading(false);});
    return()=>{alive=false;};
  },[session?.user.id,reload]);
  useEffect(()=>{
    let alive=true;setPlaces([]);setPlacesError("");
    if(selected)void businessApi.listPlaces(selected.id).then(items=>{
      if(alive)setPlaces(items.map(p=>({id:`business:${p.id}`,name:p.name,drawing:{x:p.x,y:p.y},yaw:p.yaw})));
    }).catch(e=>{if(alive)setPlacesError(e.message);});
    return()=>{alive=false;};
  },[selected?.id,reload]);
  useEffect(()=>{
    if(!online)return;
    let alive=true,timer:ReturnType<typeof setTimeout>;
    const poll=async()=>{
      try{const result=await api.getNavigationConfig();if(alive)setCalibration(previous=>JSON.stringify(previous)===JSON.stringify(result.calibration)?previous:result.calibration);}
      catch{if(alive)setError("无法读取车端导航配置，请检查小车连接和已部署服务。");}
      if(alive)timer=setTimeout(()=>void poll(),1500);
    };void poll();return()=>{alive=false;clearTimeout(timer);};
  },[api,online]);
  useEffect(()=>{
    if(locked){attempt.current="";setRegistering(false);return;}
    if(!online||mapStale){attempt.current="";setRegistering(false);return;}
    if(!expected||!online||mapStale||registered||busy){setRegistering(false);return;}
    if(attempt.current===context)return;
    attempt.current=context;const request=generation.current;let alive=true;setRegistering(true);
    // Exact grid metadata supplies this transform: no image fitting or human anchors.
    void api.calibrateNavigation(expected.anchors,key,expected.drawing).then(result=>{
      if(!alive||!mounted.current||request!==generation.current)return;
      if(!matchesDirectRegistration(result.calibration,expected))throw new Error("车端返回的 SLAM 坐标不匹配，已阻止导航");
      setCalibration(result.calibration);setRegistering(false);setError("");
    }).catch(e=>{if(alive&&mounted.current&&request===generation.current)setError(e.message);})
      .finally(()=>{if(alive&&mounted.current)setRegistering(false);});
    return()=>{alive=false;};
  },[api,context,expected?.drawing?.revision,online,mapStale,registered,locked,busy,reload]);

  const choose=(place:Place)=>{generation.current++;setTarget(place);setInitialPoint(null);setPlan(null);setError("");};
  const pick=(point:Point)=>{
    if(locked||busy||!map)return;
    if(locating){setInitialPoint(point);setLocating(false);return;}
    if(!expected||!mapConfirmed){setError("当前 SLAM 坐标尚未核对；历史地图请先加载，地图恢复后可标点。");return;}
    const problem=directPointError(map,point);if(problem){setError(problem);return;}
    choose({id:"custom",name:"自选位置",drawing:worldToDrawing(point,expected.matrix),yaw:worldYawToDrawing(status.map_pose.ok?status.map_pose.yaw:0,expected.matrix)});
  };
  const current=target&&expected?{...drawingToWorld(target.drawing,expected.matrix),yaw:drawingYawToWorld(target.yaw,expected.matrix)}:null;
  const worldPath=active?nav.path:plan?.map_key===key?plan.path:[];
  const worldGoal=active?nav.goal:current;
  const markerPlaces=expected?places.map(p=>({...drawingToWorld(p.drawing,expected.matrix),name:p.name})):[];
  async function action(work:()=>Promise<void>){
    setBusy(true);setError("");try{await work();}catch(e){if(mounted.current)setError((e as Error).message);}finally{if(mounted.current)setBusy(false);}
  }
  async function preview(){
    if(!canPlan||!current||!expected)return;
    const request=++generation.current;setPlan(null);
    await action(async()=>{const result=await api.planNavigation(current,key,calibration!.matrix,calibration!.drawing);if(mounted.current&&request===generation.current)setPlan(result);});
  }
  async function savePoint(){
    if(!selected||!target||!expected||!mapConfirmed||!name.trim())return;
    if(target.drawing.x<0||target.drawing.y<0||target.drawing.x>=selected.width||target.drawing.y>=selected.height){setError("目标超出这张已保存地图的范围，请先保存最新地图。");return;}
    await action(async()=>{
      const saved=await businessApi.savePlace(selected.id,{name:name.trim(),x:target.drawing.x,y:target.drawing.y,yaw:target.yaw});
      if(mounted.current){const place={id:`business:${saved.id}`,name:saved.name,drawing:{x:saved.x,y:saved.y},yaw:saved.yaw};setPlaces(previous=>[...previous,place]);setTarget(place);setName("");}
    });
  }
  async function saveCurrentMap(){
    if(!manage||!online||!map||locked||!mapName.trim())return;
    await action(async()=>{
      window.dispatchEvent(new Event("robot-control-stop"));
      await live.sendCommand("stop");
      const saved=await businessApi.saveSlamMap({robot_id:"r-001",request_id:saveId.current,name:mapName.trim(),floor:"1F",description:"SLAM 直接导航地图"});
      if(mounted.current){setMaps(previous=>[saved,...previous.filter(m=>m.id!==saved.id)]);rememberMap(saved.id);setSelectedId(saved.id);setMapName("");saveId.current=createMapRequestId();}
    });
  }
  const reason=!online?"连接小车后可直接使用 SLAM 地图。":mapStale?"地图数据暂不可用，请等待恢复。":!map?"尚无 SLAM 地图，请先建图或加载已保存地图。":!expected?"所选地图与车端地图不是同一会话或资产，请加载该地图并定位。":registering||!registered?"正在核对 SLAM 原始坐标，无需人工四点标定。":!status.map_pose.ok?"请先设置小车初始位置，确认定位有效。":!nav.ready?(nav.message.includes("平面图")?"正在准备 SLAM 导航坐标。":nav.message):"在 SLAM 空地上选点，先预览路线，再开始导航。";
  const feedback=active||["succeeded","canceled","failed"].includes(nav.state)?nav.message:reason;
  const changeMap=(id:string)=>{if(!locked&&!busy){rememberMap(id);setSelectedId(id);attempt.current="";}};
  return <div className="navigation-workspace direct-slam-workspace">
    <div className="navigation-heading"><div><strong>SLAM 地图与导航</strong><span>{feedback}</span></div><span className={canPlan?"alignment-state ready":"alignment-state"}>{canPlan?"可导航":mapConfirmed?"可标点 · 待导航就绪":"待就绪"}</span></div>
    <div className="drawing-source"><label>SLAM 地图<select aria-label="直接导航地图" disabled={locked||busy||catalogLoading} value={selectedId} onChange={e=>changeMap(e.target.value)}><option value="">当前 SLAM 地图（临时）</option>{maps.map(m=><option key={m.id} value={m.id}>{m.name}</option>)}</select></label><button className="btn btn-outline" aria-label="刷新 SLAM 地图" disabled={locked||busy} onClick={()=>{attempt.current="";setReload(n=>n+1);}}><RefreshCw size={14}/></button><Link className="drawing-manage" to="/maps">地图管理</Link><small>直接使用 SLAM 米制坐标；历史地图需先加载和定位。无需上传平面图。</small></div>
    {catalogError&&<p className="navigation-error" role="alert">{catalogError}</p>}
    <NavigationSetup api={api} maps={maps} online={online} locked={locked||busy||registering} locating={locating} setLocating={setLocating} initialPoint={initialPoint} selectedMapId={selectedId} onSelectMap={changeMap} direct/>
    <div className="navigation-layout"><div className="navigation-map"><LiveMapCanvas path={worldPath} goal={initialPoint||worldGoal} places={registered?markerPlaces:[]} onPick={pick}/>
      <div className="navigation-map-note">{selected?`地点绑定：${selected.name}`:"当前地图未保存，目标仅供本次使用；保存地图后可长期保存地点。"} · 障碍物、未知区和车体安全距离由车端检查。</div>
    </div><aside className="navigation-panel">
      <div className="navigation-panel-title"><MapPin size={17}/><strong>地点与目标</strong></div>
      <div className="navigation-places">{places.length===0&&<p className="navigation-hint">点击 SLAM 地图的已知空地设置目标。</p>}{places.map((p,i)=><div key={p.id}><button className={target?.id===p.id?"navigation-place selected":"navigation-place"} disabled={!mapConfirmed||locked||busy} onClick={()=>choose(p)}><span>{i+1}</span>{p.name}</button>{manage&&selected&&<button className="navigation-delete" aria-label={`删除${p.name}`} disabled={locked||busy} onClick={()=>void action(async()=>{await businessApi.deletePlace(selected.id,p.id.slice(9));setPlaces(previous=>previous.filter(item=>item.id!==p.id));if(target?.id===p.id){setTarget(null);setPlan(null);}})}><Trash2 size={13}/></button>}</div>)}</div>
      <div className="navigation-target"><span>当前目的地</span><strong>{active?"正在执行导航":target?.name||"点击 SLAM 地图选点"}</strong>{current&&<small>X {current.x.toFixed(2)} m · Y {current.y.toFixed(2)} m</small>}</div>
      {target&&current&&expected&&!locked&&<label className="navigation-yaw">到达朝向（SLAM 坐标）<input aria-label="SLAM 到达朝向" type="number" min={-180} max={180} value={Math.round(current.yaw*180/Math.PI)} onChange={e=>{const value=Number(e.target.value);if(Number.isFinite(value))choose({...target,yaw:worldYawToDrawing(value*Math.PI/180,expected.matrix)});}}/><small>沿 X 正方向 0°，沿 Y 正方向 90°</small></label>}
      {plan&&!active&&<div className="navigation-distance"><span>路线长度</span><strong>{plan.distance.toFixed(2)} m</strong></div>}
      <button className="btn btn-outline navigation-action" disabled={!target||!canPlan} onClick={()=>void preview()}>{plan?"重新预览路线":"预览路线"}</button>
      <button className="btn btn-primary navigation-action" disabled={!plan||!canPlan||plan.map_key!==key} onClick={()=>void action(async()=>{window.dispatchEvent(new Event("robot-control-stop"));await api.startNavigation(plan!.plan_id);setPlan(null);})}><Navigation size={15}/>开始导航</button>
      <button className="btn btn-outline navigation-action navigation-stop" disabled={!online||!active&&!busy} onClick={()=>{generation.current++;void action(async()=>{await api.cancelNavigation();setPlan(null);});}}><Square size={14}/>停止导航</button>
      <p className="navigation-hint" role="status">{feedback}</p>
      {placesError&&<p className="navigation-hint" role="status">地点读取失败：{placesError}</p>}
      <details className="navigation-save"><summary><Plus size={14}/>保存为地点</summary>{selected?<><label htmlFor="slam-place-name">地点名称</label><input id="slam-place-name" maxLength={40} placeholder="例如：门口、充电点" value={name} onChange={e=>setName(e.target.value)}/><button className="btn btn-outline" disabled={!manage||!target||!mapConfirmed||!name.trim()||busy||locked} onClick={()=>void savePoint()}>保存 SLAM 地点</button></>:<p className="navigation-hint">先将当前地图保存，再保存地点。</p>}</details>
    </aside></div>
    {!selected&&<details className="direct-map-save navigation-save"><summary>保存当前 SLAM 地图</summary><label htmlFor="direct-map-name">地图名称</label><input id="direct-map-name" value={mapName} maxLength={128} onChange={e=>setMapName(e.target.value)} placeholder="例如：实验室一楼"/><button className="btn btn-outline" disabled={!manage||!online||!map||!mapName.trim()||busy||locked} onClick={()=>void saveCurrentMap()}>保存地图</button></details>}
    <details className="navigation-task-disclosure" open={tasksExpanded||taskActive} onToggle={e=>setTasksExpanded(e.currentTarget.open)}><summary>文件运输与多点巡航<span>{taskActive?"任务执行中":"展开配置任务"}</span></summary><NavigationTaskPanel api={api} online={online} aligned={canPlan} calibration={registered?calibration:null} drawing={expected?.drawing||BUILTIN_DRAWING} mapKey={key} target={expected?target:null} mapId={selected?.id} controlSessionId={map?.session_id} onActive={setTaskActive}/></details>
    {error&&<div className="navigation-error" role="alert">{error}</div>}
  </div>;
}
