import { useEffect, useMemo, useState } from "react";
import { HeaderBar } from "./components/HeaderBar";
import { LidarPanel } from "./components/LidarPanel";
import { LiveCameraPanel, type VideoState } from "./components/LiveCameraPanel";
import { MapPanel } from "./components/MapPanel";
import { ModeFocusPanel } from "./components/ModeFocusPanel";
import { ModeOperationPanel } from "./components/ModeOperationPanel";
import { PerceptionHealthPanel } from "./components/PerceptionHealthPanel";
import { PreDriveChecklist } from "./components/PreDriveChecklist";
import { QuickResultCard } from "./components/QuickResultCard";
import { Sidebar } from "./components/Sidebar";
import { StatusCard } from "./components/StatusCard";
import { baseStatusCards, modes, quickResults, type ModeId } from "./data/consoleData";
import { useRobotState } from "./useRobotState";

function isModeId(mode: string): mode is ModeId {
  return modes.some((item) => item.id === mode);
}

function App() {
  const robot = useRobotState();
  const [jsonExpanded, setJsonExpanded] = useState(false);
  const [videoRevision, setVideoRevision] = useState(0);
  const [videoState, setVideoState] = useState<VideoState>("loading");
  const [mappingRestarting, setMappingRestarting] = useState(false);
  const [mappingSaving, setMappingSaving] = useState(false);
  const [mappingSavePath, setMappingSavePath] = useState("");
  const currentMode: ModeId = isModeId(robot.status.mode) ? robot.status.mode : "stop";
  const currentModeInfo = modes.find((mode) => mode.id === currentMode) ?? modes[0];
  const speed = Math.round(robot.status.speed_scale * 100);
  const colorOffset = robot.status.color_target?.offset;

  const statusCards = useMemo(() => baseStatusCards.map((card) => {
    if (card.key === "mode") return { ...card, value: currentModeInfo.name, description: currentModeInfo.description };
    if (card.key === "interlock") return {
      ...card,
      value: robot.status.emergency_stop ? "急停" : "正常",
      description: `急停 ${robot.status.emergency_stop ? "true" : "false"}`
    };
    if (card.key === "distance") return {
      ...card,
      value: robot.status.front_distance == null ? "--" : `${robot.status.front_distance.toFixed(2)} m`
    };
    if (card.key === "offset") return {
      ...card,
      value: (colorOffset ?? robot.status.lane_offset ?? 0).toFixed(3)
    };
    return card;
  }), [colorOffset, currentModeInfo, robot.status.emergency_stop, robot.status.front_distance, robot.status.lane_offset]);

  const quickCards = useMemo(() => quickResults.map((card) => {
    if (card.key === "command") return { ...card, value: robot.status.last_command || "stop", description: "来自后端状态" };
    if (card.key === "yolo") return { ...card, value: robot.status.detection || "无目标", description: "/vision/detection" };
    const target = robot.status.color_target;
    return {
      ...card,
      value: target?.visible ? `visible ${(target.offset ?? 0).toFixed(4)}` : "未检测",
      description: "/vision/color_target"
    };
  }), [robot.status.color_target, robot.status.detection, robot.status.last_command]);

  const invoke = (promise: Promise<unknown>) => { void promise.catch(() => undefined); };

  useEffect(() => {
    if (currentMode === "mapping" && robot.status.speed_scale > 0.25) {
      void robot.setSpeed(0.25).catch(() => undefined);
    }
  }, [currentMode, robot, robot.status.speed_scale]);

  const restartMapping = () => {
    setMappingRestarting(true);
    void robot.restartMapping().finally(() => {
      window.setTimeout(() => setMappingRestarting(false), 1200);
    });
  };
  const saveMapping = () => {
    setMappingSaving(true);
    void robot.saveMapping()
      .then((result) => setMappingSavePath(result.yaml_path))
      .catch(() => setMappingSavePath(""))
      .finally(() => setMappingSaving(false));
  };

  return (
    <div className="app-shell">
      <Sidebar currentMode={currentMode} connection={robot.connection} onModeChange={(mode) => invoke(robot.setMode(mode))} />
      <main className="console">
        <HeaderBar
          emergency={robot.status.emergency_stop}
          updatedAt={robot.status.updated_at}
          error={robot.error}
          onEmergency={() => invoke(robot.setEmergencyStop(!robot.status.emergency_stop))}
        />

        <section className="status-grid">
          {statusCards.map((card) => (
            <StatusCard
              key={card.key}
              title={card.title}
              value={card.value}
              description={card.description}
              icon={card.icon}
              variant={card.key === "interlock" && robot.status.emergency_stop ? "danger" : card.key === "interlock" ? "success" : "normal"}
            />
          ))}
        </section>

        <section className="dashboard-grid">
          <div className="left-column">
            <LiveCameraPanel
              revision={videoRevision}
              state={videoState}
              onStateChange={setVideoState}
              onReconnect={() => { setVideoState("loading"); setVideoRevision((value) => value + 1); }}
            />
            <div className="quick-grid">
              {quickCards.map((card) => (
                <QuickResultCard key={card.key} title={card.title} value={card.value} description={card.description} icon={card.icon} />
              ))}
            </div>
            <PerceptionHealthPanel
              expanded={jsonExpanded}
              onToggle={() => setJsonExpanded((value) => !value)}
              status={robot.status}
              connection={robot.connection}
              videoState={videoState}
            />
          </div>

          <div className="right-column">
            <ModeFocusPanel
              currentMode={currentMode}
              status={robot.status}
              restartingMapping={mappingRestarting}
            />
            <ModeOperationPanel
              currentMode={currentMode}
              status={robot.status}
              speed={speed}
              onSpeedChange={(value) => invoke(robot.setSpeed(value / 100))}
              onCommand={(command) => invoke(robot.sendCommand(command))}
              onColorConfig={(config) => invoke(robot.setColorConfig(config))}
            />
            <MapPanel
              map={robot.status.map}
              lidar={robot.status.lidar}
              odom={robot.status.odom}
              cmdVel={robot.status.cmd_vel}
              tf={robot.status.tf}
              mapPose={robot.status.map_pose}
              mappingQuality={robot.status.mapping_quality}
              lastCommand={robot.status.last_command}
              active={currentMode === "mapping"}
              speed={speed}
              restarting={mappingRestarting}
              saving={mappingSaving}
              savePath={mappingSavePath}
              onRestart={restartMapping}
              onSave={saveMapping}
            />
            <LidarPanel points={robot.status.radar_points} frontDistance={robot.status.front_distance} lidar={robot.status.lidar} />
          </div>
        </section>

        <PreDriveChecklist status={robot.status} connection={robot.connection} videoState={videoState} />
      </main>
    </div>
  );
}

export default App;
