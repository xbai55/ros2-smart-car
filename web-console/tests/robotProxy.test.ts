import assert from "node:assert/strict";
import test from "node:test";
import { ROBOT_API_PROXY_PATTERN } from "../src/robotProxy";

test("camera frame query and other vehicle requests reach the car proxy", () => {
  const route = new RegExp(ROBOT_API_PROXY_PATTERN);
  for (const url of ["/api/video?frame=true&revision=2", "/api/video", "/api/status", "/api/map?revision=10", "/api/command", "/api/mapping/restart", "/api/navigation/path?map_key=current"]) {
    assert.equal(route.test(url), true, url);
  }
});

test("business APIs and unrelated paths are not routed to the car", () => {
  const route = new RegExp(ROBOT_API_PROXY_PATTERN);
  for (const url of ["/api/v1/robots", "/api/video-extra", "/api/map/files", "/api/speedy", "/assets/camera.png"]) {
    assert.equal(route.test(url), false, url);
  }
});
