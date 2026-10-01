import assert from "node:assert/strict";
import test from "node:test";
import {
  impactScore, impactTier, jalali, groupSources, rangeFor, linkedAssets, digits,
} from "../lib/reader.js";

test("impact scores map to five tiers and missing scores stay unassessed", () => {
  const tier = (score) => impactTier(score)?.level ?? null;
  assert.deepEqual([0, 19, 20, 39, 40, 59, 60, 79, 80, 100].map(tier), [1, 1, 2, 2, 3, 3, 4, 4, 5, 5]);
  assert.equal(tier(null), null);
  assert.equal(tier(undefined), null);
  assert.equal(impactTier(85).fa, "خیلی زیاد");
  assert.equal(impactTier(10).en, "Very low");
  assert.equal(impactScore({ iran_score: 90, global_score: 40 }), 70);
  assert.equal(impactScore({ iran_score: null, global_score: 40 }), 40);
  assert.equal(impactScore({}), null);
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
