import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";
import { loadServerModule } from "./helpers.mjs";

test("malformed query boundaries render contextual recovery states", async () => {
  const [api, primitives, feed, ops, market, article] = await Promise.all([
    readFile(new URL("../lib/api.js", import.meta.url), "utf8"),
    readFile(new URL("../components/primitives.js", import.meta.url), "utf8"),
    readFile(new URL("../app/articles/page.js", import.meta.url), "utf8"),
    readFile(new URL("../app/ops/page.js", import.meta.url), "utf8"),
    readFile(new URL("../app/market/page.js", import.meta.url), "utf8"),
    readFile(new URL("../app/article/[id]/page.js", import.meta.url), "utf8"),
  ]);
  assert.match(primitives, /export function QueryError\(/);
  assert.match(feed, /error instanceof ApiError && error\.status === 400/);
  assert.match(ops, /title="Invalid time window\."/);
  assert.match(market, /catalog\.results\.some\(\(asset\) => asset\.key === params\?\.symbol\)/);
  assert.match(market, /RANGES\.includes\(params\?\.range\)/);
  assert.match(article, /if \(!\/\^\[1-9\]\\d\*\$\/.test\(id\)\) notFound\(\);/);
  assert.match(article, /error\.status === 400 \|\| error\.status === 404/);
});

test("a bad API response reaches route recovery as a structured status error", async () => {
  const api = await loadServerModule("../lib/api.js", {
    process: { env: {} },
    fetch: async () => ({ ok: false, status: 400, text: async () => '{"detail":"invalid"}' }),
  }, {
    "next/headers": {
      cookies: async () => ({ get: () => undefined }),
      headers: async () => new Headers(),
    },
    "next/navigation": { redirect: () => { throw new Error("unexpected redirect"); } },
  });

  await assert.rejects(api.apiGet("/api/market/?symbol=invalid"), (error) => {
    assert.ok(error instanceof api.ApiError);
    assert.equal(error.status, 400);
    assert.equal(error.path, "/api/market/?symbol=invalid");
    return true;
  });
});

test("a signed-in user is not sent to login for a forbidden staff route", async () => {
  const api = await loadServerModule("../lib/api.js", {
    process: { env: {} },
    fetch: async () => ({ ok: false, status: 403, text: async () => '{"detail":"forbidden"}' }),
  }, {
    "next/headers": {
      cookies: async () => ({ get: () => ({ value: "synthetic-token" }) }),
      headers: async () => new Headers({ "x-pathname": "/review" }),
    },
    "next/navigation": { redirect: () => { throw new Error("unexpected redirect"); } },
  });

  await assert.rejects(api.apiGet("/api/reviews/next/"), (error) => {
    assert.ok(error instanceof api.ApiError);
    assert.equal(error.status, 403);
    return true;
  });
});

test("the staff guard preserves an API outage instead of reporting a signed-out session", async () => {
  const api = await loadServerModule("../lib/api.js", {
    process: { env: {} },
    fetch: async () => ({ ok: false, status: 503, text: async () => "unavailable" }),
  }, {
    "next/headers": {
      cookies: async () => ({ get: () => ({ value: "synthetic-token" }) }),
      headers: async () => new Headers({ "x-pathname": "/review" }),
    },
    "next/navigation": { redirect: () => { throw new Error("unexpected redirect"); } },
  });

  await assert.rejects(api.currentStaffUser(), (error) => {
    assert.ok(error instanceof api.ApiError);
    assert.equal(error.status, 503);
    return true;
  });
});
