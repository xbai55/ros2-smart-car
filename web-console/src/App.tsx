import { useEffect } from "react";
import { matchRoute, usePath } from "./lib/router";
import { GlobalHeader } from "./components/navigation/GlobalHeader";
import { HomePage } from "./pages/home";
import { LoginPage } from "./pages/login";
import { RobotsPage, RobotDetailPage, RobotRunPage } from "./pages/robots";
import { TasksPage, TaskDetailPage } from "./pages/tasks";
import { IncidentsPage, IncidentDetailPage } from "./pages/incidents";
import { MapsPage, MapDetailPage, RoutesPage, RouteDetailPage } from "./pages/maps";
import { AnalyticsPage } from "./pages/analytics";
import { DiagnosticsPage } from "./pages/diagnostics";
import { SystemPage } from "./pages/system";
import { AssetsPage } from "./pages/assets";
import { SettingsPage } from "./pages/settings";
import { EmptyState } from "./components/ui";
import { SlamPage } from "./pages/slam";
import { AssistantPet } from "./components/AssistantPet";
import { AssistantConversation } from "./components/AssistantConversation";
import { useBusinessSession } from "./hooks/useBusinessSession";
import { AssistantReportPage } from "./pages/assistantReport";

function renderRoute(path: string) {
  let params: Record<string, string> | null;
  if (path === "/") return <HomePage />;
  if ((params = matchRoute("/assistant/reports/:id", path))) return <AssistantReportPage id={params.id} />;
  if (path === "/slam") return <SlamPage />;
  if (path === "/robots") return <RobotsPage />;
  if ((params = matchRoute("/robots/:id/run", path))) return <RobotRunPage id={params.id} />;
  if ((params = matchRoute("/robots/:id", path))) return <RobotDetailPage id={params.id} />;
  if (path === "/tasks") return <TasksPage />;
  if ((params = matchRoute("/tasks/:id", path))) return <TaskDetailPage id={params.id} />;
  if (path === "/incidents") return <IncidentsPage />;
  if ((params = matchRoute("/incidents/:id", path))) return <IncidentDetailPage id={params.id} />;
  if (path === "/maps") return <MapsPage />;
  if ((params = matchRoute("/maps/:id", path))) return <MapDetailPage id={params.id} />;
  if (path === "/routes") return <RoutesPage />;
  if ((params = matchRoute("/routes/:id", path))) return <RouteDetailPage id={params.id} />;
  if (path === "/analytics") return <AnalyticsPage />;
  if ((params = matchRoute('/system/diagnostics/executions/:id', path))) return <DiagnosticsPage executionId={params.id} />;
  if ((params = matchRoute('/system/diagnostics/tasks/:id', path))) return <DiagnosticsPage initialTask={params.id} />;
  if (path === '/system/diagnostics') return <DiagnosticsPage />;
  if (path === "/system") return <SystemPage />;
  if (path === "/assets") return <AssetsPage />;
  if (path === "/settings") return <SettingsPage />;
  return (
    <div className="page">
      <EmptyState title="页面不存在" hint="请从顶部导航进入业务模块" />
    </div>
  );
}

function AssistantHistory() {
  const session = useBusinessSession();
  if (!session?.user.role?.permissions.some(p => p.name === "assistant.read")) {
    return <div className="page"><EmptyState title="无权查看助手历史" /></div>;
  }
  return <div className="page"><h1>助手历史</h1><AssistantConversation canSend={false} /></div>;
}

export default function App() {
  const session = useBusinessSession();
  const requestedPath = usePath();
  const path = requestedPath === "/radar" ? "/slam" : requestedPath;
  useEffect(() => {
    if (requestedPath === "/radar") window.location.replace("#/slam");
    window.scrollTo(0, 0);
  }, [requestedPath]);
  if (path === "/login") return <LoginPage />;
  return (
    <div className="app-root">
      <GlobalHeader />
      <main className="app-main">{path === "/assistant/history" ? <AssistantHistory key={session?.user.id} /> : renderRoute(path)}</main>
      {session && <AssistantPet key={session.user.id} user={session.user} />}
    </div>
  );
}
