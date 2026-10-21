import { useState } from 'react';
import { businessApi, type RosMapPair } from '../../services/businessApi';
import { navigate } from '../../lib/router';
import { Button } from '../ui';
import { MapDialog } from './MapManager';

async function pair(pgm:File,yaml:File):Promise<RosMapPair>{
  if(pgm.size>40*1024*1024||yaml.size>65536)throw new Error('PGM 最大 40 MB，YAML 最大 64 KB');
  const bytes=new Uint8Array(await pgm.arrayBuffer());let binary='';
  for(let i=0;i<bytes.length;i+=8192)binary+=String.fromCharCode(...bytes.subarray(i,i+8192));
  return {filename:pgm.name,yaml:await yaml.text(),pgm_base64:btoa(binary)};
}

export function RosMapImport({onClose}:{onClose:()=>void}){
  const [name,setName]=useState(''),[files,setFiles]=useState<(File|null)[]>([null,null,null,null]);
  const [busy,setBusy]=useState(false),[error,setError]=useState('');
  async function submit(){if(!files[0]||!files[1])return;setBusy(true);setError('');try{
    if(!!files[2]!==!!files[3])throw new Error('禁行遮罩需要同时提供 PGM 和 YAML');
    const map=await pair(files[0],files[1]),mask=files[2]&&files[3]?await pair(files[2],files[3]):undefined;
    const result=await businessApi.importRosMap(name.trim(),map,mask);navigate(`/maps/${result.id}`);onClose();
  }catch(e){setError((e as Error).message);}finally{setBusy(false);}}
  return <MapDialog title="导入 ROS 地图" busy={busy} onClose={onClose}><form className="map-form" onSubmit={e=>{e.preventDefault();void submit();}}>
    <p className="map-help">导入地图不会加载到小车。支持 P2/P5 PGM 和 trinary YAML；YAML 的 image 应与所选 PGM 文件名相同。禁行遮罩可选，须同尺寸、同原点和比例。</p>
    <label>地图名称<input required maxLength={128} value={name} disabled={busy} onChange={e=>setName(e.target.value)}/></label>
    {['地图 PGM','地图 YAML','禁行遮罩 PGM（可选）','禁行遮罩 YAML（可选）'].map((label,i)=><label key={label}>{label}<input type="file" required={i<2} accept={i%2?'.yaml,.yml':'.pgm'} disabled={busy} onChange={e=>setFiles(values=>values.map((f,n)=>n===i?e.target.files?.[0]||null:f))}/></label>)}
    {error&&<p className="map-error" role="alert">{error}</p>}<div className="map-form-actions"><Button disabled={busy} onClick={onClose}>取消</Button><Button type="submit" variant="primary" disabled={busy||!name.trim()||!files[0]||!files[1]}>{busy?'正在校验并导入…':'导入为新地图'}</Button></div>
  </form></MapDialog>;
}
