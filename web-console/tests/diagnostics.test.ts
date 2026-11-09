import assert from "node:assert/strict";
import { test } from "node:test";
import { mergeDiagnostics, type DiagnosticEvent } from "../src/diagnosticsState.ts";

const event = (id: string, at: string) => ({ event_id: id, occurred_at: at }) as DiagnosticEvent;
test("late records are placed by occurrence and replayed event IDs are deduplicated", () => {
  const latest = event("new", "2026-11-09T01:00:00Z");
  const older = event("old", "2026-11-09T00:00:00Z");
  assert.deepEqual(mergeDiagnostics([latest], [older, latest]), [latest, older]);
  assert.deepEqual(mergeDiagnostics([latest], [older, latest], 1), [latest]);
});
