import assert from "node:assert/strict";
import test from "node:test";

import {
  enhancedDisplayValue,
  FREE_VALUE,
  OBSTACLE_VALUE,
  stableSquareViewBox,
  UNKNOWN_VALUE,
} from "../src/mapDisplay.ts";

test("enhanced map replaces isolated obstacle noise with surrounding free space", () => {
  const width = 5;
  const height = 5;
  const cells = Array(width * height).fill(FREE_VALUE);
  cells[2 * width + 2] = OBSTACLE_VALUE;

  assert.equal(enhancedDisplayValue(cells, width, height, 2, 2), FREE_VALUE);
});

test("enhanced map replaces isolated obstacle noise in unknown area with unknown color class", () => {
  const width = 5;
  const height = 5;
  const cells = Array(width * height).fill(UNKNOWN_VALUE);
  cells[2 * width + 2] = OBSTACLE_VALUE;

  assert.equal(enhancedDisplayValue(cells, width, height, 2, 2), UNKNOWN_VALUE);
});

test("enhanced map visually bridges a one-cell obstacle gap", () => {
  const width = 5;
  const height = 3;
  const cells = Array(width * height).fill(FREE_VALUE);
  cells[1 * width + 1] = OBSTACLE_VALUE;
  cells[1 * width + 3] = OBSTACLE_VALUE;

  assert.equal(enhancedDisplayValue(cells, width, height, 2, 1), OBSTACLE_VALUE);
});

test("stable square viewBox pads wide maps without changing map coordinates", () => {
  assert.equal(stableSquareViewBox(57, 46), "0 -5.5 57 57");
});

test("stable square viewBox pads tall maps without changing map coordinates", () => {
  assert.equal(stableSquareViewBox(32, 106), "-37 0 106 106");
});

test("stable square viewBox uses a safe minimum for empty dimensions", () => {
  assert.equal(stableSquareViewBox(0, 0), "0 0 1 1");
});
