import test from "node:test";
import assert from "node:assert/strict";
import { acceptTaskState } from "../src/navigationTaskState";

test("a late running poll cannot undo a newer cancellation", () => {
  const cancelled = { run_id: "one", state: "cancelled", message: "cancel", version: 5, updated_at: 50 };
  assert.equal(acceptTaskState(cancelled, { ...cancelled, state: "running", version: 4, updated_at: 40 }), cancelled);
});

test("a delayed previous run cannot replace a newly created run", () => {
  const next = { run_id: "new", state: "waiting_load", message: "load", version: 1, updated_at: 60 };
  assert.equal(acceptTaskState(next, { run_id: "old", state: "completed", message: "done", version: 10, updated_at: 50 }), next);
});
