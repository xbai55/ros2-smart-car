import { useEffect } from "react";
import { useData } from "../hooks/useData";
import { useRobotStream } from "../hooks/useRobotStream";
import { adapters } from "../services/adapters";
import { uiStore } from "../stores/uiStore";
import { RobotCamera } from "../components/robot/RobotCamera";
import { RobotControl } from "../components/robot/RobotControl";
import { LiveMapCanvas } from "../components/robot/LiveMapCanvas";
import { RadarPanel } from "../components/robot/RadarPanel";
import { LIVE_ROBOT_ID } from "../liveControl";
import { LiveFeedback } from "../components/robot/LiveFeedback";
import { RobotStatusPanel } from "../components/robot/RobotStatusPanel";
import {
  HeroSection,
  IncidentPanel,
  RecentObjectsPanel,
  RobotStatusStrip,
  SystemOverviewPanel,
  TaskCenterPanel,
} from "../components/workspace/HomeSections";
import { EmptyState, Panel, Skeleton } from "../components/ui";

export function HomePage() {
  const robotsQuery = useData(() => adapters.listRobots());
  const tasksQuery = useData(() => adapters.listTasks());
  const incidentsQuery = useData(() => adapters.listIncidents());
  const activityQuery = useData(() => adapters.listActivity());
  const { status, connection, setMode, setEmergencyStop, setSpeed } = useRobotStream();

  const robots = robotsQuery.data ?? [];
  const selectedId = uiStore.use().selectedRobotId;
  const robot = robots.find((r) => r.id === selectedId) ?? robots.find((r) => r.health === "online") ?? robots[0];

  const bound = robot?.id === LIVE_ROBOT_ID;
  const online = bound && connection === "connected";
  const mode = online ? status.mode : "stop";
  const speed = online ? Math.round(status.speed_scale * 100) : 15;
  const distance = online ? status.front_distance : null;

  useEffect(() => {
    if (!selectedId && robot) uiStore.set({ selectedRobotId: robot.id });
  }, [selectedId, robot]);

  return (
    <div className="page home-page">
      <HeroSection robots={robots} incidents={incidentsQuery.data} tasks={tasksQuery.data} />

      <p className="data-source-note">状态、视频和地图来自实车；任务与异常来自已保存的业务记录。</p>
      {bound && <LiveFeedback/>}
      <section className="home-main">
        <div className="home-primary">
          {robot ? <RobotCamera robot={robot} className="home-camera" /> : <Skeleton className="camera-skeleton" />}
          <div className="home-operations">
          {robot ? <RobotStatusPanel robot={robot} live={online ? status : null} connected={online} /> : null}
          <Panel title="快速控制" kicker="Control" className="home-control-panel" bodyClassName="panel-flush">
            <RobotControl
              connected={online}
              mode={mode}
              emergency={online ? status.emergency_stop : false}
              speed={speed}
              onMode={setMode}
              onEmergency={() => setEmergencyStop(!(online && status.emergency_stop))}
              onSpeed={setSpeed}
              onEnterFull={() => { window.location.hash = robot ? `/robots/${robot.id}/run` : "/robots"; }}
            />
          </Panel>
          </div>
        </div>
        <aside className="home-side" aria-label="实时地图与环境扫描">
          <Panel kicker="Live Map" title="实时地图" className="home-map-panel" bodyClassName="panel-flush" action={<span className="panel-live">{online ? "实车在线" : "等待实车连接"}</span>}>
            <LiveMapCanvas/>
          </Panel>
          <RadarPanel className="home-radar-panel" />
        </aside>
      </section>

      <section className="home-bottom">
        {tasksQuery.error ? <Panel title="任务中心"><EmptyState title="任务数据不可用" hint={tasksQuery.error}/></Panel> : <TaskCenterPanel tasks={tasksQuery.data ?? []} />}
        {incidentsQuery.error ? <Panel title="异常告警"><EmptyState title="异常数据不可用" hint={incidentsQuery.error}/></Panel> : <IncidentPanel incidents={incidentsQuery.data ?? []} />}
        {activityQuery.error ? <Panel title="最近动态"><EmptyState title="动态数据不可用" hint={activityQuery.error}/></Panel> : <RecentObjectsPanel activity={activityQuery.data ?? []} />}
        <SystemOverviewPanel />
      </section>

      <RobotStatusStrip robot={robot} connected={online} mode={mode} speed={speed} distance={distance} />
    </div>
  );
}
