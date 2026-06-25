import { Gauge, Home, RotateCcw } from "lucide-react";
import { useCallback, useEffect, useRef } from "react";
import type { CSSProperties, PointerEvent } from "react";
import { manualCommands, modes, type ModeId } from "../data/consoleData";
import { HudPanel } from "./HudPanel";

type Props = {
  currentMode: ModeId;
  speed: number;
  onSpeedChange: (speed: number) => void;
  onCommand: (command: string) => void;
};

const HOLD_REPEAT_MS = 180;

export function ManualControlPanel({ currentMode, speed, onSpeedChange, onCommand }: Props) {
  const modeName = modes.find((mode) => mode.id === currentMode)?.name ?? "停止";
  const subtitle = currentMode === "mapping" ? "建图安全遥控" : "手动遥控";
  const onCommandRef = useRef(onCommand);
  const activeCommandRef = useRef<string | null>(null);
  const repeatTimerRef = useRef<number | null>(null);

  useEffect(() => {
    onCommandRef.current = onCommand;
  }, [onCommand]);

  const sendCommand = useCallback((command: string) => {
    onCommandRef.current(command);
  }, []);

  const clearRepeatTimer = useCallback(() => {
    if (repeatTimerRef.current !== null) {
      window.clearInterval(repeatTimerRef.current);
      repeatTimerRef.current = null;
    }
  }, []);

  const stopHold = useCallback((sendStop = true) => {
    const hadActiveCommand = activeCommandRef.current !== null;
    activeCommandRef.current = null;
    clearRepeatTimer();
    if (sendStop && hadActiveCommand) sendCommand("stop");
  }, [clearRepeatTimer, sendCommand]);

  const startHold = useCallback((command: string) => {
    if (command === "stop") {
      stopHold(false);
      sendCommand("stop");
      return;
    }

    stopHold(false);
    activeCommandRef.current = command;
    sendCommand(command);
    repeatTimerRef.current = window.setInterval(() => {
      const activeCommand = activeCommandRef.current;
      if (activeCommand) sendCommand(activeCommand);
    }, HOLD_REPEAT_MS);
  }, [sendCommand, stopHold]);

  const handlePointerDown = useCallback((event: PointerEvent<HTMLButtonElement>, command: string) => {
    event.preventDefault();
    event.currentTarget.setPointerCapture(event.pointerId);
    startHold(command);
  }, [startHold]);

  const handlePointerUp = useCallback((event: PointerEvent<HTMLButtonElement>) => {
    if (event.currentTarget.hasPointerCapture(event.pointerId)) {
      event.currentTarget.releasePointerCapture(event.pointerId);
    }
    stopHold();
  }, [stopHold]);

  useEffect(() => {
    const handleWindowStop = () => stopHold();
    window.addEventListener("blur", handleWindowStop);
    window.addEventListener("pointerup", handleWindowStop);
    window.addEventListener("pointercancel", handleWindowStop);
    return () => {
      window.removeEventListener("blur", handleWindowStop);
      window.removeEventListener("pointerup", handleWindowStop);
      window.removeEventListener("pointercancel", handleWindowStop);
      stopHold();
    };
  }, [stopHold]);

  return (
    <HudPanel className="manual-panel" title="Manual Control" subtitle={subtitle} action={<span className="tag-pill">/api/command</span>}>
      <div className="manual-layout">
        <div className="drive-pad">
          {manualCommands.map((command) => {
            const Icon = command.icon;
            return (
              <button
                key={command.id}
                type="button"
                className={`drive-btn ${command.slot} ${command.danger ? "danger" : ""}`}
                onPointerDown={(event) => handlePointerDown(event, command.id)}
                onPointerUp={handlePointerUp}
                onPointerCancel={() => stopHold()}
                onLostPointerCapture={() => stopHold()}
                onKeyDown={(event) => {
                  if ((event.key === "Enter" || event.key === " ") && activeCommandRef.current !== command.id) {
                    event.preventDefault();
                    startHold(command.id);
                  }
                }}
                onKeyUp={(event) => {
                  if (event.key === "Enter" || event.key === " ") {
                    event.preventDefault();
                    stopHold();
                  }
                }}
                title={command.label}
                aria-label={command.label}
              >
                <Icon size={22} />
                <span>{command.label}</span>
              </button>
            );
          })}
        </div>
        <div className="speed-console">
          <div className="speed-head">
            <span>速度比例</span>
            <strong>{speed}%</strong>
          </div>
          <input
            type="range"
            min="15"
            max="100"
            value={speed}
            aria-label="速度比例"
            onChange={(event) => onSpeedChange(Number(event.currentTarget.value))}
            style={{ "--speed": `${speed}%` } as CSSProperties}
          />
          <button className="mini-btn" type="button" onClick={() => onSpeedChange(15)}>
            <RotateCcw size={14} />
            设为安全低速
          </button>
          <div className="speed-facts">
            <p><Gauge size={15} />最低速度 <strong>15%</strong></p>
            <p><Home size={15} />当前模式 <strong>{modeName}</strong></p>
            <p>命令通过 <strong className="green-text">FastAPI / ROS2</strong></p>
          </div>
        </div>
      </div>
    </HudPanel>
  );
}
