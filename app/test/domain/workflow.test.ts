import { test } from "node:test";
import assert from "node:assert/strict";
import {
  JOB_ACTIONS, JOB_STATUSES, allowedActions, canAdvance, isJobAction, isJobStatus, statusAfterAction,
} from "../../src/domain/workflow.ts";

test("the six statuses and five actions are fixed", () => {
  assert.deepEqual([...JOB_STATUSES], ["received", "processing", "ready", "held", "failed", "closed"]);
  assert.deepEqual([...JOB_ACTIONS], ["send_to_review", "reprocess", "hold", "close", "reopen"]);
});

test("a person can move a job exactly as the documented table says", () => {
  const expected: Record<string, string[]> = {
    send_to_review: ["received", "held", "failed"],
    reprocess: ["processing", "ready", "held", "failed", "closed"],
    hold: ["received", "ready", "failed"],
    close: ["received", "processing", "ready", "held", "failed"],
    reopen: ["closed"],
  };
  for (const action of JOB_ACTIONS) {
    const from = JOB_STATUSES.filter((status) => statusAfterAction(status, action) !== null);
    assert.deepEqual(from, JOB_STATUSES.filter((s) => expected[action].includes(s)), action);
  }
});

test("each action leads to its status", () => {
  assert.equal(statusAfterAction("received", "send_to_review"), "ready");
  assert.equal(statusAfterAction("ready", "reprocess"), "processing");
  assert.equal(statusAfterAction("ready", "hold"), "held");
  assert.equal(statusAfterAction("ready", "close"), "closed");
  assert.equal(statusAfterAction("closed", "reopen"), "ready");
});

test("an invalid action leads nowhere", () => {
  assert.equal(statusAfterAction("closed", "close"), null);
  assert.equal(statusAfterAction("received", "reopen"), null);
});

test("allowedActions lists exactly the valid actions", () => {
  assert.deepEqual(allowedActions("closed"), ["reprocess", "reopen"]);
  assert.deepEqual(allowedActions("processing"), ["reprocess", "close"]);
});

test("the pipeline only moves forward", () => {
  assert.equal(canAdvance("received", "processing"), true);
  assert.equal(canAdvance("processing", "ready"), true);
  assert.equal(canAdvance("processing", "failed"), true);
  assert.equal(canAdvance("received", "held"), true);
  assert.equal(canAdvance("ready", "received"), false);
  assert.equal(canAdvance("closed", "processing"), false);
  assert.equal(canAdvance("received", "ready"), false);
});

test("type guards reject anything unknown", () => {
  assert.equal(isJobStatus("ready"), true);
  assert.equal(isJobStatus("READY"), false);
  assert.equal(isJobStatus(42), false);
  assert.equal(isJobAction("close"), true);
  assert.equal(isJobAction("delete"), false);
});
