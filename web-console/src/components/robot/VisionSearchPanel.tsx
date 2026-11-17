import {useEffect,useRef,useState} from 'react';
import {useRobotStream} from '../../hooks/useRobotStream';
import type {SearchStatus,VisionStatus,VisionSettings} from '../../robotApi';
import type {NavigationConfig} from '../../labNavigation';
import {mapKey} from '../../labNavigation';
import {createMapRequestId} from '../../services/businessApi';

export function VisionSearchPanel() {
  const {api,status,connection,mapSnapshot}=useRobotStream();
  const [vision,setVision]=useState<VisionStatus|null>(null),[search,setSearch]=useState<SearchStatus|null>(null);
  const [settings,setSettings]=useState<VisionSettings|null>(null),[config,setConfig]=useState<NavigationConfig|null>(null);
  const [name,setName]=useState('服务器机柜'),[prompt,setPrompt]=useState('server rack'),[travel,setTravel]=useState('stationary');
  const request = useRef<{key:string; id:string} | null>(null);
  const [observe, setObserve] = useState<{executable:boolean; reasons:string[]} | null>(null);
  const [patrolSearch, setPatrolSearch] = useState<typeof observe>(null);
  const [places,setPlaces]=useState<string[]>([]),[busy,setBusy]=useState(false),[error,setError]=useState('');
  const [unsupported,setUnsupported]=useState(false),[clutter,setClutter]=useState('bottle, cardboard box, bag, backpack, chair');
  const online=connection==='connected';
  useEffect(()=>{
    if(!online)return;
    let stopped=false,timer:ReturnType<typeof setTimeout>;
    async function poll(){
      try {
        const [v,s,c]=await Promise.all([api.getVision(),api.getSearch(),api.getSearchCapabilities()]);
        if(!stopped){setVision(v);setSearch(s);setObserve(c.observe_target);setPatrolSearch(c.patrol_search);setUnsupported(false);}
      } catch(e) {if(!stopped){setObserve(null);setPatrolSearch(null);setUnsupported(true);setError((e as Error).message);}}
      if(!stopped)timer=setTimeout(()=>void poll(),1000);
    }
    void poll();
    void api.getVisionSettings().then(v=>{if(!stopped){setSettings(v);setClutter(v.clutter_prompts.join(', '));}}).catch(()=>{});
    void api.getNavigationConfig().then(v=>{if(!stopped)setConfig(v);}).catch(()=>{});
    return()=>{stopped=true;clearTimeout(timer);};
  },[api,online]);
  const active=!!search&&!['idle','finished','cancelled','not_found'].includes(search.state);
  const capability = travel === 'patrol' ? patrolSearch : observe;
  const resumeCapability = search?.travel === 'patrol' ? patrolSearch : observe;
  async function act(action:string){
    setBusy(true);setError('');
    try {
      if(action==='start'){
        const calibration=config?.calibration;
        const patrol=travel==='patrol'?{
          map_key:mapSnapshot?mapKey(mapSnapshot):'',calibration_matrix:calibration?.matrix,
          calibration_drawing:calibration?.drawing,control_session_id:mapSnapshot?.session_id,
          waypoints:config?.places.filter(p=>places.includes(p.id)).map(p=>({name:p.name,drawing:p.drawing,yaw:p.yaw})),
        }:undefined;
        const draft = {targets:[{name,prompt}],travel,patrol};
        const key = JSON.stringify(draft);
        if (request.current?.key !== key) request.current = {key, id:createMapRequestId()};
        setSearch(await api.startSearch({...draft, run_id:request.current.id}));
        request.current = null;
      } else if(search?.run_id)setSearch(await api.searchAction(search.run_id,action));
    }catch(e){setError((e as Error).message);}finally{setBusy(false);}
  }
  return <section className="motion-setting" aria-label="视觉目标搜索">
    <div className="setting-title"><strong>YOLOE‑11s 视觉搜索</strong><span>{!online?'未连接':unsupported?'车端不支持':vision?.state==='running'?'模型已就绪':'等待识别模型'}</span></div>
    <label>目标名称<input aria-label="搜索目标名称" value={name} onChange={e=>setName(e.target.value)} disabled={active||busy}/></label>
    <label>英文提示<input aria-label="目标英文提示" value={prompt} onChange={e=>setPrompt(e.target.value)} disabled={active||busy} placeholder="例如 oscilloscope；内置中文词可留空"/></label>
    <label>搜索方式<select aria-label="搜索方式" value={travel} disabled={active||busy} onChange={e=>setTravel(e.target.value)}><option value="stationary">静止观察 · 最长5分钟</option><option value="patrol">地图巡逻 · 一轮</option></select></label>
    {travel==='patrol'&&<fieldset disabled={active||busy}><legend>按已保存地点顺序巡逻</legend>{config?.places.map(p=><label key={p.id}><input type="checkbox" checked={places.includes(p.id)} onChange={e=>setPlaces(v=>e.target.checked?[...v,p.id]:v.filter(x=>x!==p.id))}/>{p.name}</label>)}{!config?.places.length&&<p>请先在地图中保存巡逻地点。</p>}</fieldset>}
    <div className="setting-presets"><button disabled={!online||unsupported||busy||active||!capability?.executable||status.mode!=='stop'||vision?.state!=='running'||!name.trim()||(travel==='patrol'&&(!places.length||!config?.calibration||!mapSnapshot))} onClick={()=>void act('start')}>开始搜索</button>
      {search?.state==='searching'&&<button disabled={busy} onClick={()=>void act('pause')}>暂停</button>}
      {search&&['found','paused'].includes(search.state)&&<button disabled={busy||!online||!resumeCapability?.executable||vision?.state!=='running'} onClick={()=>void act('continue')}>继续搜索</button>}
      {active&&<button disabled={busy||!online} onClick={()=>void act('cancel')}>结束并停车</button>}</div>
    <p role="status">{search?.message??vision?.message??'等待车端状态'}</p>
    {capability && !capability.executable && <p>{'当前搜索方式尚未就绪，请检查实时状态'}</p>}
    {search?.evidence&&<p>{search.evidence.save_error?'已停车，但证据保存失败':'已保存目标画面及车辆位置'}</p>}
    <details><summary>普通物品标注设置</summary><label><input type="checkbox" checked={settings?.clutter_enabled??false} disabled={!online||!settings||active||status.mode!=='stop'||busy} onChange={e=>{setBusy(true);void api.setVisionSettings({clutter_enabled:e.target.checked}).then(setSettings).catch(e=>setError(e.message)).finally(()=>setBusy(false));}}/>仅在画面中标注，不生成异常提醒</label>
      <label>英文类别，以逗号分隔<input value={clutter} disabled={active||busy||status.mode!=='stop'} onChange={e=>setClutter(e.target.value)}/></label>
      <button disabled={!settings||!online||active||busy||status.mode!=='stop'} onClick={()=>{setBusy(true);void api.setVisionSettings({clutter_prompts:clutter.split(',').map(v=>v.trim()).filter(Boolean)}).then(setSettings).catch(e=>setError(e.message)).finally(()=>setBusy(false));}}>保存类别</button></details>
    {vision?.detections.map((v,i)=><p key={i}>{v.label} · {(v.confidence*100).toFixed(0)}% {v.passage??''}</p>)}
    <p className="setting-note">确认搜索目标后在当前位置停车，不自动靠近。普通物品只标框；通道异常需要通道区域证据，雷达避障独立运行。</p>
    {error&&<p role="alert">{error}</p>}
  </section>;
}
