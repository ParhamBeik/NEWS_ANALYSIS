import assert from "node:assert/strict";
import test from "node:test";
import {
  tierMeta, jalali, groupSources, rangeFor, linkedAssets, digits,
} from "../lib/reader.js";

test("API tiers 1-5 get labels and a missing tier stays unassessed", () => {
  assert.deepEqual([1, 2, 3, 4, 5].map((level) => tierMeta(level).level), [1, 2, 3, 4, 5]);
  assert.equal(tierMeta(5).fa, "خیلی زیاد");
  assert.equal(tierMeta(1).en, "Very low");
  for (const missing of [null, undefined, 0, 6, 2.5, ""]) assert.equal(tierMeta(missing), null);
});

test("dates are Jalali in both languages with Persian digits in Persian", () => {
  const iso = "2026-10-01T10:00:00Z"; // 13:30 Tehran, 9 Mehr 1405
  assert.equal(jalali(iso, "fa"), "۹ مهر ۱۴۰۵، ۱۳:۳۰");
  assert.equal(jalali(iso, "en"), "9 Mehr 1405, 13:30");
  assert.equal(jalali(iso, "fa", { time: false }), "۹ مهر ۱۴۰۵");
  // Tehran midnight boundary: 21:00Z on 21 March is already 1 Farvardin.
  assert.equal(jalali("2026-03-20T21:00:00Z", "en", { time: false }), "1 Farvardin 1405");
  assert.equal(jalali(null, "fa"), "—");
  assert.equal(digits(1234, "fa"), "۱٬۲۳۴");
});

test("sources group by outlet and the market window covers the event", () => {
  const groups = groupSources([{ name: "mehr" }, { name: "isna" }, { name: "mehr" }]);
  assert.deepEqual(groups.map((group) => [group.name, group.items.length]), [["mehr", 2], ["isna", 1]]);
  const now = Date.parse("2026-10-01T00:00:00Z");
  assert.equal(rangeFor("2026-09-30T00:00:00Z", now), "1W");
  assert.equal(rangeFor("2026-09-10T00:00:00Z", now), "1M");
  assert.equal(rangeFor("2025-01-01T00:00:00Z", now), "1Y");
  const catalog = [{ key: "usd_irr", class: "fx" }, { key: "gold_18k", class: "gold" }];
  assert.deepEqual(linkedAssets({ gold: 80, fx: 60 }, catalog).map((a) => a.key), ["gold_18k", "usd_irr"]);
  assert.equal(linkedAssets({}, catalog).length, 2);
});
