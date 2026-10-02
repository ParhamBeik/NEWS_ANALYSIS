import assert from "node:assert/strict";
import test from "node:test";
import { WATCH_BOOST, boostWatched } from "../lib/reader.js";
import { loadServerModule } from "./helpers.mjs";

const event = (id, slugs = []) => ({ id, watch_items: slugs.map((slug) => ({ slug })) });

test("watched events are marked and lifted a bounded number of places", () => {
  const events = Array.from({ length: 10 }, (_, index) => event(index, index === 7 ? ["usd_irr"] : []));
  const boosted = boostWatched(events, ["usd_irr"]);
  assert.equal(boosted.findIndex((row) => row.id === 7), 7 - WATCH_BOOST);
  assert.equal(boosted[0].id, 0, "a watched story does not jump over everything");
  assert.equal(boosted.find((row) => row.id === 7).watched, true);
  assert.equal(boosted.filter((row) => row.watched).length, 1);
  // Latest-first order is only marked, never reordered.
  assert.deepEqual(boostWatched(events, ["usd_irr"], { boost: false }).map((row) => row.id), events.map((row) => row.id));
  assert.deepEqual(boostWatched(events, []).map((row) => row.id), events.map((row) => row.id));
});

async function phoneActions(reply) {
  const calls = [];
  const stored = [];
  const actions = await loadServerModule("../app/login/actions.js", {
    process: { env: {} },
    fetch: async (url, options) => { calls.push({ url, body: JSON.parse(options.body) }); return reply(url); },
  }, {
    "next/headers": { cookies: async () => ({ set: (...args) => stored.push(args) }), headers: async () => new Headers() },
    "next/navigation": { redirect: (to) => { throw Object.assign(new Error("redirect"), { to }); } },
    "@/lib/api": { API_ORIGIN: "http://backend:8000" },
  });
  return { actions, calls, stored };
}

function form(fields) {
  const data = new FormData();
  for (const [key, value] of Object.entries(fields)) data.set(key, value);
  return data;
}

test("phone sign-in asks for a code, then verifies and sends a new reader to onboarding", async () => {
  const { actions, calls, stored } = await phoneActions((url) => url.endsWith("/request/")
    ? { ok: true, status: 202, json: async () => ({ sent: true }) }
    : { ok: true, status: 201, json: async () => ({ token: "tok", onboarded: false }) });
  const first = await actions.phoneLogin(null, form({ phone: "09121234567" }));
  assert.equal(first.step, "code");
  assert.equal(calls[0].url, "http://backend:8000/api/auth/otp/request/");
  await assert.rejects(actions.phoneLogin(null, form({ phone: "09121234567", code: "123456" })),
    (error) => error.to === "/onboarding");
  assert.deepEqual(calls[1].body, { phone: "09121234567", code: "123456" });
  assert.equal(stored[0][0], "news_token");
  assert.equal(stored[0][2].httpOnly, true);
  // "Send again" requests a new code even with a half-typed one in the form.
  await actions.phoneLogin(null, form({ phone: "09121234567", code: "12", resend: "1" }));
  assert.equal(calls[2].url, "http://backend:8000/api/auth/otp/request/");
});

test("phone sign-in shows the API's refusal in Persian and keeps the right step", async () => {
  const { actions } = await phoneActions(() => ({ ok: false, status: 400, json: async () => ({ error: "invalid_code" }) }));
  const wrong = await actions.phoneLogin(null, form({ phone: "09121234567", code: "000000" }));
  assert.equal(wrong.step, "code");
  assert.match(wrong.error, /کد نادرست/);
  const { actions: off } = await phoneActions(() => ({ ok: false, status: 503, json: async () => ({ error: "sms_unavailable" }) }));
  const down = await off.phoneLogin(null, form({ phone: "09121234567", lang: "en" }));
  assert.equal(down.step, "phone");
  assert.match(down.error, /not available/);
});
