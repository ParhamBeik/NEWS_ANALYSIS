import assert from "node:assert/strict";
import test from "node:test";
import { loadServerModule } from "./helpers.mjs";

test("swipe gestures and keys map to review actions", async () => {
  const { gestureAction, keyAction } = await loadServerModule("../lib/swipe.js", {}, {});
  assert.equal(gestureAction(120, 10), "agree");
  assert.equal(gestureAction(-120, 10), "fix");
  assert.equal(gestureAction(40, 0), null, "a short drag is a tap, not a decision");
  assert.equal(gestureAction(100, 140), null, "a vertical scroll is not a decision");

  assert.equal(keyAction({ key: "ArrowRight" }), "agree");
  assert.equal(keyAction({ key: "ArrowLeft" }), "fix");
  assert.equal(keyAction({ key: "ArrowDown" }), "skip");
  assert.equal(keyAction({ key: "z", metaKey: true }), "undo");
  assert.equal(keyAction({ key: "Z", ctrlKey: true }), "undo");
  assert.equal(keyAction({ key: "ArrowRight", altKey: true }), null);
  assert.equal(keyAction({ key: "a" }), null);
});
