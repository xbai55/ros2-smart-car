import assert from "node:assert/strict";
import test from "node:test";
import { MAP_MARKERS, svgScreenScale } from "../src/mapViewport";

test("small and large maps keep markers the same screen size at every zoom", () => {
  for (const [width, height] of [[85,50],[1208,552],[2000,4000]]) {
    for (const screen of [{width:580,height:350},{width:900,height:480},{width:340,height:340}]) {
      for (const zoom of [.7,1,4]) {
        const view={width:width*1.1/zoom,height:height*1.2/zoom};
        const scale=svgScreenScale(view,screen);
        const markerRadius=MAP_MARKERS.halo/scale;
        assert.ok(Math.abs(markerRadius*scale-19)<1e-8);
        assert.ok(Math.abs(MAP_MARKERS.robot/scale*scale-12)<1e-8);
      }
    }
  }
});

test("SVG letterboxing uses the constrained axis for both markers and panning", () => {
  assert.equal(svgScreenScale({width:100,height:400},{width:800,height:200}),.5);
  assert.equal(svgScreenScale({width:400,height:100},{width:200,height:800}),.5);
});
