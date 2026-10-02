import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";
import { loadServerModule } from "./helpers.mjs";

const source = (path) => readFile(new URL(path, import.meta.url), "utf8");

test("privacy and terms open for a signed-out visitor", async () => {
  const middleware = await loadServerModule("../middleware.js", {}, {
    "next/server": { NextResponse: { next: () => "continue", redirect: () => "redirect" } },
  });
  for (const path of ["/privacy", "/terms"]) {
    assert.equal(middleware.middleware({
      nextUrl: new URL(`http://localhost${path}`), cookies: { get: () => undefined },
      headers: new Headers(), url: `http://localhost${path}`,
    }), "continue", path);
  }
});

test("legal pages state the locked privacy and content decisions in both languages", async () => {
  const [privacy, terms, shell, login] = await Promise.all([
    source("../app/privacy/page.js"), source("../app/terms/page.js"),
    source("../components/AppShell.js"), source("../app/login/page.js"),
  ]);
  for (const [text, words] of [
    [privacy, ["mobile number", "optional", "watchlist", "push tokens", "no third-party analytics", "within 30 days",
      "شمارهٔ موبایل", "۳۰ روز", "ردیاب شخص ثالث"]],
    [terms, ["Not investment advice", "forecast", "attributed", "link out", "توصیهٔ سرمایه‌گذاری نیست", "پیش‌بینی"]],
  ]) {
    for (const word of words) assert.ok(text.includes(word), word);
  }
  for (const page of [shell, login]) {
    assert.match(page, /href="\/privacy"/);
    assert.match(page, /href="\/terms"/);
  }
});
