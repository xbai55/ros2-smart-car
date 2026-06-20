import type { ColorConfig } from "./robotApi";

const COLOR_KEY = "smart-car.color-config";
type StorageLike = Pick<Storage, "getItem" | "setItem">;

function isTriplet(value: unknown): value is [number, number, number] {
  return Array.isArray(value) && value.length === 3 && value.every((item) => Number.isFinite(Number(item)));
}

export function colorConfigKey(config: ColorConfig) {
  return `${config.name}|${config.hsv_low.join(",")}|${config.hsv_high.join(",")}`;
}

export function loadSavedColor(storage: StorageLike): ColorConfig | null {
  try {
    const value = JSON.parse(storage.getItem(COLOR_KEY) ?? "null") as Partial<ColorConfig> | null;
    if (!value || typeof value.name !== "string" || !isTriplet(value.hsv_low) || !isTriplet(value.hsv_high)) return null;
    return { name: value.name, hsv_low: value.hsv_low.map(Number) as ColorConfig["hsv_low"], hsv_high: value.hsv_high.map(Number) as ColorConfig["hsv_high"] };
  } catch {
    return null;
  }
}

export function saveColor(storage: StorageLike, config: ColorConfig) {
  storage.setItem(COLOR_KEY, JSON.stringify(config));
}
