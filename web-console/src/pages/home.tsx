import { useEffect } from "react";
import { useData } from "../hooks/useData";
import { useRobotStream } from "../hooks/useRobotStream";
import { adapters } from "../services/adapters";
import { uiStore } from "../stores/uiStore";
import { RobotCamera } from "../components/robot/RobotCamera";
import { RobotControl } from "../components/robot/RobotControl";
import { RobotMapCanvas } from "../components/robot/RobotMapCanvas";
import { RobotStatusPanel } from "../components/robot/RobotStatusPanel";
import {
  HeroSection,
  IncidentPanel,
  RecentObjectsPanel,
  RobotStatusStrip,
  SystemOverviewPanel,
  TaskCenterPanel,
} from "../components/workspace/HomeSections";
import { Panel, Skeleton } from "../components/ui";

export function HomePage() {
  const robotsQuery = useData(() => adapters.listRobots());
  const tasksQuery = useData(() => adapters.listTasks());
  const incidentsQuery = useData(() => adapters.listIncidents());
  const activityQuery = useData(() => adapters.listActivity());
  const { status, connection, setMode, setEmergencyStop, setSpeed } = useRobotStream();

  const robots = robotsQuery.data ?? [];
  const selectedId = uiStore.use().selectedRobotId;
  const robot = robots.find((r) => r.id === selectedId) ?? robots.find((r) => r.health === "online") ?? robots[0];

  const mode = connection === "connected" ? status.mode : (robot?.mode ?? "stop");
  const speed = connection === "connected" ? Math.round(status.speed_scale * 100) : (robot?.speed ?? 0);
  const distance = connection === "connected" ? status.front_distance : (robot?.frontDistance ?? null);

  useEffect(() => {
    if (!selectedId && robot) uiStore.set({ selectedRobotId: robot.id });
  }, [selectedId, robot]);

  return (
    <div className="page home-page">
      <HeroSection robots={robots} incidents={incidentsQuery.data ?? []} tasks={tasksQuery.data ?? []} />

      <section className="home-main">
        <div className="home-map-wrap">
          <Panel kicker="Live Map" title="实时地图" className="home-map-panel" bodyClassName="panel-flush" action={<span className="panel-live"><i className="live-pulse" />{robots.filter((r) => r.health === "online").length} 在线</span>}>
            {robots.length ? <RobotMapCanvas robots={robots} incidents={incidentsQuery.data ?? []} /> : <Skeleton className="map-skeleton" />}
          </Panel>
        </div>
        <aside className="home-side">
          {robot ? <RobotCamera robot={robot} /> : <Skeleton className="camera-skeleton" />}
          {robot ? <RobotStatusPanel robot={robot} live={connection === "connected" ? status : null} connected={connection === "connected"} /> : null}
          <Panel title="快速控制" kicker="Control" className="home-control-panel" bodyClassName="panel-flush">
            <RobotControl
              connected={connection === "connected"}
              mode={mode}
              emergency={connection === "connected" ? status.emergency_stop : false}
              speed={speed}
              onMode={setMode}
              onEmergency={() => setEmergencyStop(!(connection === "connected" && status.emergency_stop))}
              onSpeed={setSpeed}
              onEnterFull={() => { window.location.hash = robot ? `/robots/${robot.id}/run` : "/robots"; }}
            />
          </Panel>
        </aside>
      </section>

      <section className="home-bottom">
        <TaskCenterPanel tasks={tasksQuery.data ?? []} />
        <IncidentPanel incidents={incidentsQuery.data ?? []} />
        <RecentObjectsPanel activity={activityQuery.data ?? []} />
        <SystemOverviewPanel />
      </section>

      <RobotStatusStrip robot={robot} connected={connection === "connected"} mode={mode} speed={speed} distance={distance} />
    </div>
  );
}
