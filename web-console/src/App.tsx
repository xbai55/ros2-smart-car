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
import { SystemPage } from "./pages/system";
import { AssetsPage } from "./pages/assets";
import { SettingsPage } from "./pages/settings";
import { EmptyState } from "./components/ui";
import { SlamPage } from "./pages/slam";

function renderRoute(path: string) {
  let params: Record<string, string> | null;
  if (path === "/") return <HomePage />;
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
  if (path === "/system") return <SystemPage />;
  if (path === "/assets") return <AssetsPage />;
  if (path === "/settings") return <SettingsPage />;
  return (
    <div className="page">
      <EmptyState title="页面不存在" hint="请从顶部导航进入业务模块" />
    </div>
  );
}

export default function App() {
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
      <main className="app-main">{renderRoute(path)}</main>
    </div>
  );
}
