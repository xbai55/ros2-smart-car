import assert from "node:assert/strict";
import test from "node:test";

import { hasDecodedVideoFrame, shouldStartVideo, videoStateAfterTimeout } from "../src/videoState.ts";
test("multipart streams become ready when their first frame is decoded",()=>{
  assert.equal(hasDecodedVideoFrame(640,480),true);
  assert.equal(hasDecodedVideoFrame(0,480),false);
  assert.equal(hasDecodedVideoFrame(NaN,480),false);
});

test("a video stream still loading after the watchdog becomes an error", () => {
  assert.equal(videoStateAfterTimeout("loading"), "error");
  assert.equal(videoStateAfterTimeout("connected"), "connected");
});

test("video starts only after the document load completes", () => {
  assert.equal(shouldStartVideo("loading"), false);
  assert.equal(shouldStartVideo("complete"), true);
});
