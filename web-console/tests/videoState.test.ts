import assert from "node:assert/strict";
import test from "node:test";

import { shouldStartVideo, videoStateAfterTimeout } from "../src/videoState.ts";

test("a video stream still loading after the watchdog becomes an error", () => {
  assert.equal(videoStateAfterTimeout("loading"), "error");
  assert.equal(videoStateAfterTimeout("connected"), "connected");
});

test("video starts only after the document load completes", () => {
  assert.equal(shouldStartVideo("loading"), false);
  assert.equal(shouldStartVideo("complete"), true);
});
