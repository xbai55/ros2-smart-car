import {
  AlertTriangle,
  BarChart3,
  Bell,
  Bot,
  Boxes,
  ChevronDown,
  Clock,
  LayoutDashboard,
  ListChecks,
  LogOut,
  Map as MapIcon,
  Search,
  Settings,
  ShieldCheck,
  User as UserIcon,
} from "lucide-react";
import { useEffect, useMemo, useRef, useState } from "react";
import { useData } from "../../hooks/useData";
import { adapters } from "../../services/adapters";
import { uiStore } from "../../stores/uiStore";
import type { Incident, MapObject, NotificationItem, Robot, Task } from "../../types/domain";
import { cn } from "../../lib/cn";
import { Link, usePath } from "../../lib/router";

type MegaLink = { label: string; href: string; desc?: string; icon?: typeof Bot };

type NavItem = {
  id: string;
  label: string;
  href: string;
  icon: typeof Bot;
  mega?: { title: string; desc: string; items: MegaLink[]; footer: { label: string; href: string } };
};

const navItems: NavItem[] = [
  { id: "workbench", label: "工作台", href: "/", icon: LayoutDashboard },
  {
    id: "robots", label: "机器人", href: "/robots", icon: Bot,
    mega: {
      title: "机器人", desc: "实验室巡检与运输车队的运行与调度",
      items: [
        { label: "我的机器人", href: "/robots", desc: "查看全部在线与离线机器人" },
        { label: "运行工作区", href: "/robots/r-001", desc: "进入 SLAM 地图与实时控制" },
        { label: "遥测与日志", href: "/robots/r-001", desc: "传感器、位姿与节点健康" },
      ],
      footer: { label: "进入机器人中心", href: "/robots" },
    },
  },
  {
    id: "tasks", label: "任务", href: "/tasks", icon: ListChecks,
    mega: {
      title: "任务中心", desc: "巡检与文件运输任务的统一编排",
      items: [
        { label: "巡检任务", href: "/tasks", desc: "实验室安全巡检计划与执行" },
        { label: "运输任务", href: "/tasks", desc: "文件取件、运输与交接流程" },
        { label: "进行中", href: "/tasks/t-101", desc: "查看当前执行进度" },
      ],
      footer: { label: "进入任务中心", href: "/tasks" },
    },
  },
  {
    id: "incidents", label: "异常", href: "/incidents", icon: AlertTriangle,
    mega: {
      title: "异常中心", desc: "AI 检测事件与人工处理闭环",
      items: [
        { label: "未处理", href: "/incidents", desc: "需要确认的告警" },
        { label: "现场证据", href: "/incidents/i-301", desc: "图像、检测框与地图位置" },
        { label: "处理时间线", href: "/incidents/i-302", desc: "确认、处置与关闭记录" },
      ],
      footer: { label: "进入异常中心", href: "/incidents" },
    },
  },
  {
    id: "maps", label: "地图", href: "/maps", icon: MapIcon,
    mega: {
      title: "地图与路线", desc: "OccupancyGrid 地图与巡检路线",
      items: [
        { label: "地图列表", href: "/maps", desc: "管理建图成果与版本" },
        { label: "路线管理", href: "/routes", desc: "巡检与运输路线编辑" },
        { label: "图层与对象", href: "/maps/m-001", desc: "地图详情与图层控制" },
      ],
      footer: { label: "进入地图中心", href: "/maps" },
    },
  },
  {
    id: "analytics", label: "数据", href: "/analytics", icon: BarChart3,
    mega: {
      title: "数据洞察", desc: "任务、异常与机器人运行统计",
      items: [
        { label: "统计分析", href: "/analytics", desc: "巡检/运输/异常趋势" },
        { label: "系统状态", href: "/system", desc: "资源与 ROS2 节点健康" },
      ],
      footer: { label: "进入数据中心", href: "/analytics" },
    },
  },
  {
    id: "assets", label: "资产", href: "/assets", icon: Boxes,
    mega: {
      title: "业务资产", desc: "设备、模型与媒体资料",
      items: [
        { label: "设备清单", href: "/assets", desc: "机器人、传感器与备件" },
        { label: "模型与媒体", href: "/assets", desc: "检测模型与现场记录" },
      ],
      footer: { label: "进入资产中心", href: "/assets" },
    },
  },
  {
    id: "system", label: "系统", href: "/system", icon: Settings,
    mega: {
      title: "系统", desc: "运行状态、安全与账户管理",
      items: [
        { label: "系统状态", href: "/system", desc: "CPU / GPU / 网络 / ROS2 节点" },
        { label: "用户与角色", href: "/settings", desc: "RBAC 权限与账户" },
        { label: "审计日志", href: "/settings", desc: "关键操作留痕" },
      ],
      footer: { label: "进入系统中心", href: "/system" },
    },
  },
];

function BrandMark() {
  return (
    <Link to="/" className="brand" aria-label="InsightRover 智巡首页">
      <img className="brand-logo" src="/brand/logo-mark.png" alt="InsightRover 智巡" />
    </Link>
  );
}

function NavigationMenu({ path }: { path: string }) {
  return (
    <nav className="main-nav" aria-label="一级业务导航">
      {navItems.map((item) => {
        const Icon = item.icon;
        const isActive = item.href === "/" ? path === "/" : path.startsWith(item.href);
        return (
          <div key={item.id} className={cn("nav-item", isActive && "active")}>
            <Link to={item.href} className="nav-link">
              <Icon size={16} />
              <span>{item.label}</span>
              {item.mega ? <ChevronDown size={13} className="nav-chevron" /> : null}
            </Link>
            {item.mega ? (
              <div className="mega" role="menu">
                <div className="mega-head">
                  <strong>{item.mega.title}</strong>
                  <span>{item.mega.desc}</span>
                </div>
                <div className="mega-grid">
                  {item.mega.items.map((link) => {
                    const LIcon = link.icon ?? item.icon;
                    return (
                      <Link key={link.label} to={link.href} className="mega-item">
                        <LIcon size={16} />
                        <span>
                          <strong>{link.label}</strong>
                          {link.desc ? <em>{link.desc}</em> : null}
                        </span>
                      </Link>
                    );
                  })}
                </div>
                <div className="mega-footer">
                  <Link to={item.mega.footer.href}>{item.mega.footer.label} <ChevronDown size={13} className="rotate" /></Link>
                </div>
              </div>
            ) : null}
          </div>
        );
      })}
    </nav>
  );
}

function GlobalSearch() {
  const open = uiStore.use().commandOpen;
  const setOpen = (value: boolean) => uiStore.set({ commandOpen: value });
  const [query, setQuery] = useState("");
  const [loading, setLoading] = useState(false);
  const [index, setIndex] = useState<{ robots: Robot[]; tasks: Task[]; maps: MapObject[]; incidents: Incident[] }>({ robots: [], tasks: [], maps: [], incidents: [] });
  const inputRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === "k") {
        e.preventDefault();
        setOpen(!uiStore.get().commandOpen);
      }
      if (e.key === "Escape") setOpen(false);
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);

  useEffect(() => {
    if (!open) { setQuery(""); return; }
    setLoading(true);
    Promise.all([adapters.listRobots(), adapters.listTasks(), adapters.listMaps(), adapters.listIncidents()])
      .then(([robots, tasks, maps, incidents]) => setIndex({ robots, tasks, maps, incidents }))
      .finally(() => setLoading(false));
    const t = window.setTimeout(() => inputRef.current?.focus(), 30);
    return () => window.clearTimeout(t);
  }, [open]);

  const q = query.trim().toLowerCase();
  const groups = useMemo(() => {
    const hit = (s: string) => s.toLowerCase().includes(q);
    return {
      robots: index.robots.filter((r) => !q || hit(r.name) || hit(r.zone) || hit(r.id)),
      tasks: index.tasks.filter((t) => !q || hit(t.title) || hit(t.id)),
      maps: index.maps.filter((m) => !q || hit(m.name) || hit(m.id)),
      incidents: index.incidents.filter((i) => !q || hit(i.title) || hit(i.location) || hit(i.id)),
    };
  }, [index, q]);

  if (!open) return null;

  return (
    <div className="command-overlay" onClick={() => setOpen(false)}>
      <div className="command-palette" onClick={(e) => e.stopPropagation()}>
        <div className="command-input">
          <Search size={17} />
          <input ref={inputRef} value={query} onChange={(e) => setQuery(e.target.value)} placeholder="搜索机器人、任务、地图、异常…" />
          <kbd>ESC</kbd>
        </div>
        <div className="command-results">
          {loading ? <div className="command-hint">正在索引…</div> : null}
          {!loading && !q && <div className="command-hint">输入关键词，或按方向浏览。支持 Ctrl/Cmd + K 快速唤起。</div>}
          <SearchGroup title="机器人" icon={Bot} rows={groups.robots.map((r) => ({ key: r.id, label: r.name, sub: r.zone, href: `/robots/${r.id}` }))} onPick={() => setOpen(false)} />
          <SearchGroup title="任务" icon={ListChecks} rows={groups.tasks.map((t) => ({ key: t.id, label: t.title, sub: t.robotName, href: `/tasks/${t.id}` }))} onPick={() => setOpen(false)} />
          <SearchGroup title="地图" icon={MapIcon} rows={groups.maps.map((m) => ({ key: m.id, label: m.name, sub: m.area, href: `/maps/${m.id}` }))} onPick={() => setOpen(false)} />
          <SearchGroup title="异常" icon={AlertTriangle} rows={groups.incidents.map((i) => ({ key: i.id, label: i.title, sub: i.location, href: `/incidents/${i.id}` }))} onPick={() => setOpen(false)} />
        </div>
      </div>
    </div>
  );
}

function SearchGroup({ title, icon: Icon, rows, onPick }: { title: string; icon: typeof Bot; rows: Array<{ key: string; label: string; sub: string; href: string }>; onPick: () => void }) {
  if (!rows.length) return null;
  return (
    <div className="search-group">
      <div className="search-group-title"><Icon size={14} />{title}</div>
      {rows.slice(0, 4).map((row) => (
        <Link key={row.key} to={row.href} className="search-row" onClick={onPick}>
          <span>
            <strong>{row.label}</strong>
            <em>{row.sub}</em>
          </span>
          <ChevronDown size={14} className="rotate" />
        </Link>
      ))}
    </div>
  );
}

function NotificationCenter() {
  const open = uiStore.use().notificationsOpen;
  const { data, loading } = useData(() => adapters.listNotifications());
  const items = data ?? [];
  const unread = items.filter((n) => !n.read).length;

  const iconFor = (type: NotificationItem["type"]) => (type === "incident" ? AlertTriangle : type === "task" ? ListChecks : ShieldCheck);
  const toneFor = (type: NotificationItem["type"]) => (type === "incident" ? "danger" : type === "task" ? "blue" : "info");

  return (
    <div className="tool">
      <button type="button" className="tool-btn" aria-label="通知中心" onClick={() => uiStore.set({ notificationsOpen: !open, userMenuOpen: false })}>
        <Bell size={17} />
        {unread > 0 ? <span className="tool-badge">{unread}</span> : null}
      </button>
      {open ? (
        <>
          <div className="tool-backdrop" onClick={() => uiStore.set({ notificationsOpen: false })} />
          <div className="popover notification-popover">
            <header className="popover-head">
              <strong>通知中心</strong>
              <span>{unread} 条未读</span>
            </header>
            <div className="popover-body">
              {loading ? <div className="command-hint">加载中…</div> : null}
              {!loading && items.length === 0 ? <div className="command-hint">暂无通知</div> : null}
              {items.map((n) => {
                const Icon = iconFor(n.type);
                return (
                  <Link key={n.id} to={n.href} className="notification-row" onClick={() => uiStore.set({ notificationsOpen: false })}>
                    <span className={cn("notification-icon", `tone-${toneFor(n.type)}`)}><Icon size={15} /></span>
                    <span className="notification-copy">
                      <strong>{n.title}</strong>
                      <em>{n.object}</em>
                    </span>
                    <time>{n.time}</time>
                    {!n.read ? <span className="unread-dot" /> : null}
                  </Link>
                );
              })}
            </div>
            <footer className="popover-foot">
              <Link to="/incidents" onClick={() => uiStore.set({ notificationsOpen: false })}>查看全部异常</Link>
            </footer>
          </div>
        </>
      ) : null}
    </div>
  );
}

function UserMenu() {
  const open = uiStore.use().userMenuOpen;
  return (
    <div className="tool">
      <button type="button" className="user-btn" aria-label="用户菜单" onClick={() => uiStore.set({ userMenuOpen: !open, notificationsOpen: false })}>
        <span className="avatar"><UserIcon size={15} /></span>
        <span className="user-copy"><strong>陈老师</strong><em>管理员</em></span>
        <ChevronDown size={14} />
      </button>
      {open ? (
        <>
          <div className="tool-backdrop" onClick={() => uiStore.set({ userMenuOpen: false })} />
          <div className="popover user-popover">
            <div className="user-popover-head">
              <span className="avatar lg"><UserIcon size={18} /></span>
              <div><strong>陈老师</strong><em>admin@insightrover</em></div>
            </div>
            <div className="popover-body menu-list">
              <Link to="/settings" onClick={() => uiStore.set({ userMenuOpen: false })}><UserIcon size={15} />个人中心</Link>
              <Link to="/settings" onClick={() => uiStore.set({ userMenuOpen: false })}><Settings size={15} />账户设置</Link>
              <Link to="/settings" onClick={() => uiStore.set({ userMenuOpen: false })}><ShieldCheck size={15} />权限与角色</Link>
              <Link to="/settings" onClick={() => uiStore.set({ userMenuOpen: false })}><Clock size={15} />审计日志</Link>
            </div>
            <footer className="popover-foot menu-list">
              <a href="#/login" onClick={() => uiStore.set({ userMenuOpen: false })}><LogOut size={15} />退出登录</a>
            </footer>
          </div>
        </>
      ) : null}
    </div>
  );
}

export function GlobalHeader() {
  const path = usePath();
  return (
    <header className="global-header">
      <div className="header-inner">
        <BrandMark />
        <NavigationMenu path={path} />
        <div className="header-tools">
          <button type="button" className="tool-btn search-trigger" onClick={() => uiStore.set({ commandOpen: true })} aria-label="全局搜索">
            <Search size={16} />
            <span className="search-hint">搜索</span>
            <kbd>Ctrl K</kbd>
          </button>
          <Link to="/tasks" className="tool-btn task-trigger" aria-label="任务中心">
            <ListChecks size={16} />
          </Link>
          <NotificationCenter />
          <UserMenu />
        </div>
      </div>
      <GlobalSearch />
    </header>
  );
}

