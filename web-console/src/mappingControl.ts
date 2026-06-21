import type { ModeId } from "./data/consoleData";

export function modeUsesManualControl(mode: ModeId): mode is "manual" | "mapping" {
  return mode === "manual" || mode === "mapping";
}
