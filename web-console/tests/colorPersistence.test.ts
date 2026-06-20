import assert from "node:assert/strict";
import test from "node:test";

import { colorConfigKey, loadSavedColor, saveColor } from "../src/colorPersistence.ts";

class MemoryStorage {
  values = new Map<string, string>();
  getItem(key: string) { return this.values.get(key) ?? null; }
  setItem(key: string, value: string) { this.values.set(key, value); }
}

test("saved color survives a page reload", () => {
  const storage = new MemoryStorage();
  const red = { name: "red", hsv_low: [0, 80, 80], hsv_high: [12, 255, 255] } as const;

  saveColor(storage, red);

  assert.deepEqual(loadSavedColor(storage), red);
});

test("invalid saved color falls back safely", () => {
  const storage = new MemoryStorage();
  storage.setItem("smart-car.color-config", "not json");

  assert.equal(loadSavedColor(storage), null);
});


test("equivalent websocket color snapshots have a stable identity key", () => {
  const first = { name: "green", hsv_low: [35, 60, 60], hsv_high: [90, 255, 255] } as const;
  const refreshed = { name: "green", hsv_low: [35, 60, 60], hsv_high: [90, 255, 255] } as const;

  assert.equal(colorConfigKey(first), colorConfigKey(refreshed));
});
