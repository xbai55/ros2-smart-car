import { useCallback, useEffect, useRef } from "react";
import type { PointerEvent } from "react";
import { manualCommands, type ModeId } from "../data/consoleData";

type Props = {
  currentMode: ModeId;
  speed: number;
  onSpeedChange: (speed: number) => void;
  onCommand: (command: string) => void;
};

const HOLD_REPEAT_MS = 180;

export function ManualControlPanel({ onCommand }: Props) {
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
    </div>
  );
}
