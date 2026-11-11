import assert from "node:assert/strict";
import test from "node:test";
import { applyChatEvent, currentPlan, followsLatest, mergeAssistantTurns, rememberExecution, shouldSendWithEnter,
  type ChatTurn } from "../src/components/assistant/chatState";
import { safeAssistantLink } from "../src/components/assistant/AssistantMarkdown";
import { launcherSize, placeAssistant } from "../src/components/assistant/petLayout";
import type { AssistantDraft, AssistantExecution } from "../src/services/businessApi";

test("the open assistant stays clear of the draggable launcher within the viewport", () => {
  for (const [width, height] of [[1440, 900], [1366, 768], [390, 844], [320, 420]]) {
    for (const expanded of [false, true]) {
      const viewport = {left: 0, top: 0, width, height};
      for (const point of [{x: 0, y: 0}, {x: width, y: height}, {x: width / 2, y: height / 2}]) {
        const {launcher, panel} = placeAssistant(point, viewport, 64, expanded);
        assert.ok(panel.width > 0 && panel.height > 0);
        assert.ok(panel.left >= 0 && panel.left + panel.width <= width);
        assert.ok(panel.top >= 0 && panel.top + panel.height <= height);
        assert.ok(panel.top + panel.height <= launcher.y || launcher.y + launcherSize <= panel.top ||
          panel.left + panel.width <= launcher.x || launcher.x + launcherSize <= panel.left);
      }
    }
  }
});

test("incremental replies distinguish tool failures from generation and keep partial text after interruption", () => {
  const starting: ChatTurn = {id: "message", client_id: "message", text: "状态", reply: null,
    generation: {state: "generating", text: "", tools: []}};
  const partial = applyChatEvent(starting, {kind: "delta", text: "预览"});
  const running = applyChatEvent(partial, {kind: "tool", id: 0, name: "get_robot_context", state: "running"});
  const failure = applyChatEvent(running, {kind: "tool", id: 0, name: "get_robot_context", state: "failed"});
  const next = applyChatEvent(failure, {kind: "generating"});
  assert.equal(running.generation?.state, "using_tools");
  assert.equal(running.generation?.text, "");
  assert.deepEqual(next.generation?.tools.map(tool => tool.state), ["failed"]);
  assert.equal(next.generation?.state, "generating");
  const cancelled: ChatTurn = {...partial, generation: {...partial.generation!, state: "cancelled"}};
  assert.equal(applyChatEvent(cancelled, {kind: "delta", text: "迟到的数据"}), cancelled);
});

test("a stale history fetch cannot wipe an in-flight turn or a just-completed reply", () => {
  const server = {id: "server", client_id: "client", text: "状态", reply: null};
  const pending: ChatTurn = {...server, id: "client", generation: {state: "generating", text: "部分回复", tools: []}};
  assert.deepEqual(mergeAssistantTurns([server], [pending]), [pending]);
  const completed = {...server, reply: {text: "最终回复", plan: null}};
  assert.deepEqual(mergeAssistantTurns([server], [completed]), [completed]);
  assert.deepEqual(mergeAssistantTurns([completed], [pending]), [completed]);
});

test("execution events stay attached to their plan and only advance by version", () => {
  const plan: AssistantDraft = {id: "plan-a", state: "draft", version: 1, digest: "hash", expires_at: 0, steps: []};
  const execution: AssistantExecution = {id: "task", plan_id: plan.id, robot_id: "robot", state: "running", version: 2, step_index: 0};
  const latest = rememberExecution({}, execution);
  assert.equal(rememberExecution(latest, {...execution, state: "queued", version: 1}), latest);
  const turn: ChatTurn = {id: "a", client_id: "a", text: "计划", reply: {text: "已拟定", plan}};
  assert.equal(currentPlan(turn, latest)?.execution?.state, "running");
  const unrelated = {...turn, reply: {...turn.reply!, plan: {...plan, id: "plan-b"}}};
  assert.equal(currentPlan(unrelated, latest)?.execution, undefined);
});

test("keyboard sending respects multiline editing and IME composition", () => {
  assert.equal(shouldSendWithEnter("Enter", false, false, 13), true);
  assert.equal(shouldSendWithEnter("Enter", true, false, 13), false);
  assert.equal(shouldSendWithEnter("Enter", false, true, 13), false);
  assert.equal(shouldSendWithEnter("Enter", false, false, 229), false);
});

test("scroll following applies only near the bottom", () => {
  assert.equal(followsLatest(575, 400, 1000), true);
  assert.equal(followsLatest(300, 400, 1000), false);
});

test("assistant Markdown links only accept explicit HTTP or HTTPS", () => {
  for (const link of ["javascript:alert(1)", "data:text/html,foo", "//example.com", "java\nscript:alert(1)"]) {
    assert.equal(safeAssistantLink(link), null);
  }
  assert.equal(safeAssistantLink("https://example.com/docs"), "https://example.com/docs");
});
