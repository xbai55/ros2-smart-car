import { useState } from "react";
import { useData } from "../hooks/useData";
import { useBusinessSession } from "../hooks/useBusinessSession";
import { adapters } from "../services/adapters";
import { EmptyState, Panel } from "../components/ui";
import { ObjectHeader } from "../components/shared";
const sections = ["个人中心", "用户管理", "角色与权限", "通知记录", "审计日志", "系统说明"];
export function SettingsPage() {
  const [section, setSection] = useState(sections[0]);
  return <div className="page"><ObjectHeader kicker="Settings" title="系统设置" subtitle="当前账户及业务服务保存的管理记录"/><div className="settings-layout"><nav className="settings-nav">{sections.map(s => <button key={s} className={s === section ? "on" : ""} onClick={() => setSection(s)}>{s}</button>)}</nav><div className="settings-content"><SettingsSection section={section}/></div></div></div>;
}
function SettingsSection({ section }: { section: string }) {
  const session = useBusinessSession();
  const query = useData(async () => {
    if (section === "用户管理") return (await adapters.listUsers()).map(u => ({ id: u.id, title: u.name, detail: `${u.username} · ${u.role} · ${u.status === "active" ? "启用" : "停用"}` }));
    if (section === "角色与权限") return (await adapters.listRoles()).map(r => ({ id: r.id, title: r.name, detail: `${r.description} · ${r.permissions.join("、")}` }));
    if (section === "通知记录") return (await adapters.listNotifications()).map(n => ({ id: n.id, title: n.title, detail: `${n.object} · ${n.time} · ${n.read ? "已读" : "未读"}` }));
    if (section === "审计日志") return (await adapters.listAuditLogs()).map(a => ({ id: a.id, title: a.action, detail: `${a.actor} · ${a.object} · ${a.time}` }));
    return [];
  }, [section]);
  if (section === "个人中心") return <Panel title={section}>{!session ? <EmptyState title="尚未登录" hint="登录后显示真实账户信息"/> : <div className="profile-list"><div><em>名称</em><strong>{session.user.display_name || session.user.username}</strong></div><div><em>用户名</em><strong>{session.user.username}</strong></div><div><em>角色</em><strong>{session.user.role?.name || "未分配"}</strong></div></div>}</Panel>;
  if (section === "系统说明") return <Panel title={section}><div className="profile-list"><div><em>状态来源</em><strong>车端实时状态接口与业务数据库</strong></div><div><em>急停</em><strong>运行期间锁定；服务重启后须重新核对</strong></div><div><em>导航坐标</em><strong>上传图须与当前 SLAM 地图标定后使用</strong></div><div><em>任务执行</em><strong>本页业务状态尚未接入实车执行确认</strong></div></div></Panel>;
  return <Panel title={section}>{query.loading ? <EmptyState title="加载中…"/> : query.error ? <EmptyState title="数据不可用" hint={query.error}/> : !query.data?.length ? <EmptyState title="暂无记录"/> : query.data.map(r => <div key={r.id} className="mini-row"><span><strong>{r.title}</strong><em>{r.detail}</em></span></div>)}</Panel>;
}
