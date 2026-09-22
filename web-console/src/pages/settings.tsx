import { Bell, Clock, KeyRound, ShieldCheck, UserCircle2, Users } from "lucide-react";
import { useState } from "react";
import { useData } from "../hooks/useData";
import { adapters } from "../services/adapters";
import { Badge, Panel } from "../components/ui";
import { DataTable, ObjectHeader, type Column } from "../components/shared";
import type { AuditEntry, NotificationItem, RoleItem, UserItem } from "../types/domain";

type Section = "profile" | "users" | "roles" | "notifications" | "audit" | "system";

const sections: Array<{ id: Section; label: string; icon: typeof Users }> = [
  { id: "profile", label: "个人中心", icon: UserCircle2 },
  { id: "users", label: "用户管理", icon: Users },
  { id: "roles", label: "角色与权限", icon: ShieldCheck },
  { id: "notifications", label: "通知设置", icon: Bell },
  { id: "audit", label: "审计日志", icon: Clock },
  { id: "system", label: "系统设置", icon: KeyRound },
];

export function SettingsPage() {
  const [section, setSection] = useState<Section>("profile");
  return (
    <div className="page">
      <ObjectHeader kicker="Settings" title="系统设置" subtitle="账户、权限、通知与审计等企业级管理能力" />
      <div className="settings-layout">
        <nav className="settings-nav" aria-label="设置分区">
          {sections.map((s) => {
            const Icon = s.icon;
            return (
              <button key={s.id} type="button" className={section === s.id ? "on" : ""} onClick={() => setSection(s.id)}>
                <Icon size={15} />{s.label}
              </button>
            );
          })}
        </nav>
        <div className="settings-content">
          {section === "profile" ? <ProfileSection /> : null}
          {section === "users" ? <UsersSection /> : null}
          {section === "roles" ? <RolesSection /> : null}
          {section === "notifications" ? <NotificationsSection /> : null}
          {section === "audit" ? <AuditSection /> : null}
          {section === "system" ? <SystemSection /> : null}
        </div>
      </div>
    </div>
  );
}

function ProfileSection() {
  return (
    <Panel title="个人中心" kicker="Profile">
      <div className="profile-card">
        <span className="avatar xl"><UserCircle2 size={26} /></span>
        <div><strong>陈老师</strong><em>管理员 · admin@insightrover</em></div>
      </div>
      <div className="profile-list">
        <div><em>用户名</em><strong>admin</strong></div>
        <div><em>角色</em><strong>管理员</strong></div>
        <div><em>最近登录</em><strong>今天 14:20</strong></div>
        <div><em>所属</em><strong>实验室安全巡检组</strong></div>
      </div>
    </Panel>
  );
}

function UsersSection() {
  const { data, loading } = useData(() => adapters.listUsers());
  const columns: Column<UserItem>[] = [
    { key: "name", header: "用户", render: (u) => <div className="cell-strong"><strong>{u.name}</strong><em>{u.username}</em></div> },
    { key: "role", header: "角色", render: (u) => <Badge tone="blue">{u.role}</Badge> },
    { key: "status", header: "状态", render: (u) => <Badge tone={u.status === "active" ? "success" : "neutral"}>{u.status === "active" ? "启用" : "停用"}</Badge> },
    { key: "last", header: "最近登录", render: (u) => u.lastLogin },
  ];
  return <Panel title="用户管理" kicker="Users" className="list-panel" bodyClassName="panel-flush"><DataTable columns={columns} rows={data ?? []} rowKey={(u) => u.id} loading={loading} emptyTitle="暂无用户" /></Panel>;
}

function RolesSection() {
  const { data, loading } = useData(() => adapters.listRoles());
  return (
    <Panel title="角色与权限" kicker="RBAC" className="list-panel">
      <div className="role-list">
        {loading ? <div className="chart-placeholder">加载中…</div> : null}
        {(data ?? []).map((role: RoleItem) => (
          <div key={role.id} className="role-card">
            <div className="role-card-head"><strong>{role.name}</strong><Badge tone="neutral">{role.users} 用户</Badge></div>
            <p>{role.description}</p>
            <div className="role-perms">{role.permissions.map((p) => <code key={p}>{p}</code>)}</div>
          </div>
        ))}
      </div>
    </Panel>
  );
}

function NotificationsSection() {
  const { data, loading } = useData(() => adapters.listNotifications());
  const typeLabel = (t: NotificationItem["type"]) => (t === "incident" ? "异常告警" : t === "task" ? "任务事件" : "系统通知");
  return (
    <Panel title="通知设置" kicker="Notifications" className="list-panel">
      <div className="notification-settings">
        {(data ?? []).slice(0, 5).map((n) => (
          <div key={n.id} className="notif-setting-row">
            <span><strong>{n.title}</strong><em>{typeLabel(n.type)} · {n.time}</em></span>
            <Badge tone={n.read ? "neutral" : "blue"}>{n.read ? "已读" : "未读"}</Badge>
          </div>
        ))}
        {loading ? <div className="chart-placeholder">加载中…</div> : null}
      </div>
    </Panel>
  );
}

function AuditSection() {
  const { data, loading } = useData(() => adapters.listAuditLogs());
  const columns: Column<AuditEntry>[] = [
    { key: "time", header: "时间", render: (a) => a.time },
    { key: "actor", header: "操作者", render: (a) => a.actor },
    { key: "action", header: "操作", render: (a) => a.action },
    { key: "object", header: "对象", render: (a) => a.object },
    { key: "result", header: "结果", render: (a) => <Badge tone={a.result === "success" ? "success" : "danger"}>{a.result === "success" ? "成功" : "失败"}</Badge> },
  ];
  return <Panel title="审计日志" kicker="Audit" className="list-panel" bodyClassName="panel-flush"><DataTable columns={columns} rows={data ?? []} rowKey={(a) => a.id} loading={loading} emptyTitle="暂无日志" /></Panel>;
}

function SystemSection() {
  return (
    <Panel title="系统设置" kicker="System">
      <div className="profile-list">
        <div><em>数据刷新周期</em><strong>5 秒（实时）</strong></div>
        <div><em>急停默认状态</em><strong>保持上次状态</strong></div>
        <div><em>安全仲裁</em><strong>decision_controller 独立执行</strong></div>
        <div><em>地图坐标系</em><strong>沿用项目已校准关系</strong></div>
      </div>
    </Panel>
  );
}
