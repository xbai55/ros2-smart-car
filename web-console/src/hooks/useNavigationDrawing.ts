import { useEffect, useRef, useState } from "react";
import { BUILTIN_DRAWING, type Calibration, type DrawingDescriptor, type Place } from "../labNavigation";
import { businessApi, type ManagedMap } from "../services/businessApi";
import { useBusinessSession } from "./useBusinessSession";

export function useNavigationDrawing(calibration: Calibration | null) {
  const session = useBusinessSession();
  const [maps, setMaps] = useState<ManagedMap[]>([]), [sourceId, setSourceId] = useState(BUILTIN_DRAWING.id);
  const [imageUrl, setImageUrl] = useState(""), [places, setPlaces] = useState<Place[]>([]), [error, setError] = useState("");
  const [placesError, setPlacesError] = useState(""), [loadedId, setLoadedId] = useState("");
  const [loading, setLoading] = useState(false), [reload, setReload] = useState(0);
  const [listLoading,setListLoading]=useState(!!session);
  const restored = useRef(false);
  useEffect(() => {
    let active = true; setMaps([]);
    if (!session) {setListLoading(false);return;}
    setListLoading(true);
    void Promise.all([businessApi.listMaps(), businessApi.getMapSelection()]).then(([value, selection]) => {
      if (!active) return;
      const available=value.filter(m => m.active && m.image_url && m.width > 0 && m.height > 0);
      setMaps(available);
      if (selection.map_id) {
        restored.current=true;
        if (available.some(m=>m.id===selection.map_id)) setSourceId(selection.map_id);
        else setError("已选用地图不可用，请在地图管理中重新选择");
      } else if (selection.initialized) {restored.current=true;setSourceId(BUILTIN_DRAWING.id);}
    }).catch(e => { if (active) setError(e.message); }).finally(()=>{if(active)setListLoading(false);});
    return () => { active = false; };
  }, [session?.user.id, reload]);
  useEffect(() => {
    if (restored.current || !calibration?.drawing || calibration.drawing.kind !== "uploaded" || !maps.length) return;
    restored.current = true;
    if (maps.some(m => m.id === calibration.drawing!.id)) setSourceId(calibration.drawing.id);
    else setError("已标定的上传地图已删除或当前账户无权读取，请重新选择地图");
  }, [maps, calibration]);
  const selected = maps.find(m => m.id === sourceId);
  const drawing: DrawingDescriptor = selected ? { id: selected.id, kind: "uploaded", name: selected.name, width: selected.width, height: selected.height, ...(selected.image_key ? { revision: selected.image_key } : {}) } : BUILTIN_DRAWING;
  useEffect(() => {
    let active = true, url = ""; setImageUrl(""); setPlaces([]); setError(""); setPlacesError(""); setLoadedId("");
    if (!selected) { setLoading(false); return; }
    setLoading(true);
    void businessApi.image(selected.id).then(image => {
      if (!active) return;
      url = URL.createObjectURL(image); setImageUrl(url); setLoadedId(selected.id);
    }).catch(e => { if (active) setError(e.message); }).finally(() => { if (active) setLoading(false); });
    void businessApi.listPlaces(selected.id).then(stops => {
      if (active) setPlaces(stops.map(p => ({ id: `business:${p.id}`, name: p.name, drawing: { x: p.x, y: p.y }, yaw: p.yaw })));
    }).catch(e => { if (active) setPlacesError(`地点暂未加载：${e.message}，仍可进行地图对齐`); });
    return () => { active = false; if (url) URL.revokeObjectURL(url); };
  }, [selected?.id, selected?.image_key, reload]);
  const choose = (id: string) => {
    const manage=!!session?.user.role?.permissions.some(p=>p.name==="maps.manage");
    if (!manage) { restored.current=true;setSourceId(id);return; }
    setLoading(true);setError("");
    void (id===BUILTIN_DRAWING.id?businessApi.clearMapSelection():businessApi.selectMap(id)).then(()=>{
      restored.current=true;setSourceId(id);
    }).catch(e=>setError(e.message)).finally(()=>setLoading(false));
  };
  return { maps, selected, drawing, imageUrl: loadedId === drawing.id ? imageUrl : "", places: loadedId === drawing.id ? places : [], error, placesError, loading:loading||listLoading, choose, loggedIn: !!session, refresh: () => setReload(n => n + 1) };
}
