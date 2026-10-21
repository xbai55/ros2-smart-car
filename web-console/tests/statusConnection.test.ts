import assert from "node:assert/strict";
import test from "node:test";
import { statusSocketTimedOut } from "../src/statusConnection.ts";

test("a reconnect gets its own handshake window after an old session timed out", () => {
  assert.equal(statusSocketTimedOut(0, 1000, 10000, 12000), false);
  assert.equal(statusSocketTimedOut(0, 1000, 10000, 15001), true);
});

test("open sockets must receive fresh frames; closing sockets are not closed again", () => {
  assert.equal(statusSocketTimedOut(1, 12000, 10000, 14000), false);
  assert.equal(statusSocketTimedOut(1, 12000, 10000, 14501), true);
  assert.equal(statusSocketTimedOut(1, 0, 10000, 12501), true);
  assert.equal(statusSocketTimedOut(2, 1000, 10000, 20000), false);
  assert.equal(statusSocketTimedOut(3, 1000, 10000, 20000), false);
});
