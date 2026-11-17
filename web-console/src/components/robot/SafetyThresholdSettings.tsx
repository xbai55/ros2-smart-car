import {useEffect,useState} from 'react';
import {businessApi, type SafetyThresholds} from '../../services/businessApi';
import {useBusinessSession} from '../../hooks/useBusinessSession';
export function SafetyThresholdSettings() {
 const [value,setValue]=useState<SafetyThresholds|null>(null),[pending,setPending]=useState(false),[message,setMessage]=useState('');
 const session=useBusinessSession();const editable=!!session?.user.role?.permissions.some(p=>p.name==='incidents.manage');
 useEffect(()=>{let active=true;businessApi.safetyThresholds().then(v=>{if(active)setValue(v);}).catch(e=>{if(active)setMessage(e.message);});return()=>{active=false;};},[]);
 async function save(){if(!value)return;setPending(true);setMessage('');try{setValue(await businessApi.setSafetyThresholds(value));setMessage('已保存，对后续候选及待完成复核生效');}catch(e){setMessage((e as Error).message);}finally{setPending(false);}}
 const valid=value&&Object.values(value).every(v=>[v.candidate,v.review].every(n=>Number.isFinite(n)&&n>=0&&n<=1));
 return <div><p>DS 明确支持且分数达到阈值才提示。证据不足、低分或复核失败仅保留候选记录。分数表示模型给出的证据强度，未经概率校准。</p>
 {value&&(['smoke_fire','fallen_person'] as const).map(category=><fieldset key={category}><legend>{category==='smoke_fire'?'烟火':'人员倒地'}</legend>{(['candidate','review'] as const).map(key=><label key={key}>{key==='candidate'?'候选上报最低分':'DS 告警最低分'}<input aria-label={`${category} ${key}`} type="number" min={0} max={1} step={.05} disabled={!editable||pending} value={Number.isNaN(value[category][key])?'':value[category][key]} onChange={e=>setValue({...value,[category]:{...value[category],[key]:e.target.value===''?NaN:Number(e.target.value)}})}/></label>)}</fieldset>)}
 <p>候选上报阈值仅筛选车端已检出的目标，调低不会增加车端模型的检出范围。DS 筛选需要配置并启用图片复核，未启用时仍走本地识别。运动防撞和急停独立生效。</p>
 <button type="button" className="btn btn-outline" disabled={!editable||pending||!valid} onClick={()=>void save()}>保存识别阈值</button><p role="status">{message}</p></div>;
}
