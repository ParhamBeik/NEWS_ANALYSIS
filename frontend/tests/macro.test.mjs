import assert from "node:assert/strict";
import test from "node:test";
import { POLICY_CALENDAR, direction, displayPrice, nextMeeting, sparkPath } from "../lib/macro.js";

test("rial prices are shown in toman and missing prices as a dash", () => {
  assert.deepEqual(displayPrice("2584650", "IRR", "en"), { text: "258,465", unit: "toman" });
  assert.equal(displayPrice("2584650", "IRR", "fa").unit, "تومان");
  assert.deepEqual(displayPrice("99.839", "USD/bbl", "en"), { text: "99.84", unit: "USD/bbl" });
  assert.equal(displayPrice(null, "USD", "en").text, "—");
});

test("direction is a neutral glyph and tolerates missing changes", () => {
  assert.deepEqual(["-2.44", "0.1", "0", null, "x"].map(direction), ["▼", "▲", "→", "→", "→"]);
});

test("next meeting counts whole days and banks without a schedule return null", () => {
  const fomc = POLICY_CALENDAR.find((bank) => bank.key === "fomc");
  assert.deepEqual(nextMeeting(fomc, Date.parse("2026-10-02T09:00:00Z")), { date: "2026-10-28", days: 26 });
  assert.equal(nextMeeting(fomc, Date.parse("2027-06-01T00:00:00Z")), null);
  assert.equal(nextMeeting(POLICY_CALENDAR.find((bank) => bank.key === "cbi")), null);
});

test("sparklines need two numbers and stay inside the box", () => {
  assert.equal(sparkPath(["1"]), null);
  assert.equal(sparkPath(["1", "3"], 100, 28), "M0.0,28.0 L100.0,0.0");
});
