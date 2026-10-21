import { useState } from "react";
import { useBusinessSession } from "../../hooks/useBusinessSession";
import { Link } from "../../lib/router";
import { createMapRequestId, type SlamMapDraft } from "../../services/businessApi";
import { Button } from "../ui";
import { MapDialog } from "./MapManager";

export function SaveSlamMapDialog({ onClose, onSave, error }: { onClose: () => void; onSave: (draft: SlamMapDraft) => Promise<boolean>; error: string }) {
  const session = useBusinessSession();
  const [draft, setDraft] = useState<SlamMapDraft>(() => ({ request_id: createMapRequestId(), name: `SLAM 地图 ${new Date().toLocaleString("zh-CN", { hour12: false })}`, floor: "1F", description: "" }));
  const [busy, setBusy] = useState(false), [attempted, setAttempted] = useState(false);
  const allowed = !!session?.user.role?.permissions.some(p => p.name === "maps.manage");
  return <MapDialog title="保存 SLAM 地图" onClose={onClose} busy={busy}>
    {!session ? <><p>登录后保存地图，即可在地图管理中查看、标注和选用。</p><Link className="btn btn-primary" to="/login?return=%2Fslam">登录账户</Link></> : !allowed ? <p>当前账户没有地图管理权限，请使用操作员或管理员账户保存。</p> : <form className="map-form" onSubmit={event => {
      event.preventDefault(); if (busy || !draft.name.trim()) return;
      setBusy(true); setAttempted(true);
      void onSave({ ...draft, name: draft.name.trim() }).then(ok => { if (ok) onClose(); }).finally(() => setBusy(false));
    }}>
      <p className="map-help">保存到小车，同时登记到地图管理；保留真实分辨率、原点和地图文件。</p>
      <label>地图名称<input autoFocus required maxLength={128} value={draft.name} disabled={busy} onChange={e => setDraft({ ...draft, name: e.target.value })}/></label>
      <label>楼层 / 区域<input maxLength={64} value={draft.floor} disabled={busy} onChange={e => setDraft({ ...draft, floor: e.target.value })}/></label>
      <label>备注<textarea maxLength={2000} value={draft.description} disabled={busy} onChange={e => setDraft({ ...draft, description: e.target.value })}/></label>
      {attempted && error && <p className="map-error" role="alert">{error}</p>}
      <div className="map-form-actions"><Button disabled={busy} onClick={onClose}>取消</Button><Button type="submit" variant="primary" disabled={busy || !draft.name.trim()}>{busy ? "正在保存…" : "保存到地图管理"}</Button></div>
    </form>}
  </MapDialog>;
}
