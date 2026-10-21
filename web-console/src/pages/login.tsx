import { ArrowRight, Lock, ShieldCheck, User } from "lucide-react";
import { useState } from "react";
import { navigate } from "../lib/router";
import { businessApi } from "../services/businessApi";

export function LoginPage() {
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");

  const submit = async () => {
    if (loading) return;
    setLoading(true); setError("");
    try {
      await businessApi.login(username.trim(), password);
      const requested = new URLSearchParams(window.location.hash.split("?")[1] || "").get("return");
      navigate(requested?.startsWith("/maps") ? requested : "/");
    } catch (e) { setError((e as Error).message); }
    finally { setLoading(false); }
  };

  return (
    <div className="login-page">
      <div className="login-visual">
        <div className="login-brand">
          <img className="login-logo" src="/brand/logo-mark.png" alt="InsightRover 智巡" />
        </div>
        <div className="login-scene">
          <div className="login-radar" />
          <LoginRover />
          <div className="login-floor" />
        </div>
        <div className="login-caption">
          <h2>实验室安全巡检与文件运输系统</h2>
          <p>以机器人为中心，统一管理巡检、运输、异常与地图路线。</p>
        </div>
      </div>

      <div className="login-panel">
        <form className="login-form" onSubmit={e => { e.preventDefault(); void submit(); }}>
          <h1>登录</h1>
          <p className="login-sub">使用你的系统账户进入工作台</p>
          <label className="login-field">
            <span>用户名</span>
            <div className="login-input"><User size={15} /><input required autoComplete="username" value={username} onChange={(e) => setUsername(e.target.value)} placeholder="admin" /></div>
          </label>
          <label className="login-field">
            <span>密码</span>
            <div className="login-input"><Lock size={15} /><input required autoComplete="current-password" type="password" value={password} onChange={(e) => setPassword(e.target.value)} placeholder="••••••••" /></div>
          </label>
          {error && <p role="alert" className="map-error">{error}</p>}
          <button type="submit" className="login-submit" disabled={loading}>
            {loading ? "正在进入…" : "进入工作台"} {!loading ? <ArrowRight size={16} /> : null}
          </button>
          <div className="login-foot">
            <span><ShieldCheck size={13} />安全链路由车端 decision_controller 独立仲裁</span>
          </div>
        </form>
      </div>
    </div>
  );
}

function LoginRover() {
  return (
    <svg className="login-rover" viewBox="0 0 260 150" fill="none" xmlns="http://www.w3.org/2000/svg" aria-hidden="true">
      <ellipse cx="130" cy="132" rx="96" ry="10" fill="rgba(37,99,235,.14)" />
      <g transform="translate(130,88)">
        <rect x="-66" y="-32" width="132" height="46" rx="14" fill="#1e293b" />
        <rect x="-66" y="-32" width="132" height="18" rx="9" fill="#334155" />
        <rect x="34" y="-40" width="46" height="30" rx="8" fill="#1e293b" />
        <rect x="40" y="-35" width="34" height="20" rx="6" fill="#0ea5e9" opacity=".9" />
        <circle cx="74" cy="-25" r="4.5" fill="#bae6fd" />
        <rect x="-58" y="-25" width="28" height="11" rx="4" fill="#0f172a" />
        <circle cx="0" cy="-20" r="7" fill="#2563eb" />
        <line x1="-58" y1="-16" x2="58" y2="-16" stroke="#0f172a" strokeWidth="2.5" />
        <rect x="-46" y="14" width="20" height="10" rx="2" fill="#0f172a" />
        <rect x="26" y="14" width="20" height="10" rx="2" fill="#0f172a" />
      </g>
      <circle cx="72" cy="118" r="19" fill="#1e293b" />
      <circle cx="72" cy="118" r="10" fill="#334155" />
      <circle cx="72" cy="118" r="4" fill="#94a3b8" />
      <circle cx="188" cy="118" r="19" fill="#1e293b" />
      <circle cx="188" cy="118" r="10" fill="#334155" />
      <circle cx="188" cy="118" r="4" fill="#94a3b8" />
    </svg>
  );
}
