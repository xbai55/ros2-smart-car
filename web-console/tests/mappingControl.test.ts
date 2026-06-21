import assert from "node:assert/strict";
import test from "node:test";

import { modeUsesManualControl } from "../src/mappingControl.ts";


test("manual controls are available in manual and mapping modes only", () => {
  assert.equal(modeUsesManualControl("manual"), true);
  assert.equal(modeUsesManualControl("mapping"), true);
  assert.equal(modeUsesManualControl("stop"), false);
  assert.equal(modeUsesManualControl("navigation"), false);
});
