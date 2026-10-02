import AsyncStorage from "@react-native-async-storage/async-storage";
import { ApiError, requestCode } from "../src/lib/api";
import { cleanCode, displayPhone, normalizePhone, otpMessage, otpReason, resendIn } from "../src/lib/phone";
import { boostWatched, WATCH_BOOST } from "../src/lib/reader";
import { cleanTime, groupItems } from "../src/lib/watch";
import { forgetDevice, syncDevice } from "../src/push/device";

jest.mock("@react-native-async-storage/async-storage", () =>
  require("@react-native-async-storage/async-storage/jest/async-storage-mock"));

const BASE = "https://news.example";

type Call = { url: string; method: string; body: unknown; auth: string | undefined };

function mockFetch(reply: (call: Call) => { status: number; body?: unknown } = () => ({ status: 200, body: {} })) {
  const calls: Call[] = [];
  globalThis.fetch = jest.fn(async (url: string, init: RequestInit) => {
    const headers = init.headers as Record<string, string>;
    const call = { url, method: init.method ?? "GET", body: init.body ? JSON.parse(String(init.body)) : undefined, auth: headers.Authorization };
    calls.push(call);
    const { status, body } = reply(call);
    return { ok: status < 400, status, statusText: "", json: async () => body } as Response;
  }) as unknown as typeof fetch;
  return calls;
}

describe("phone sign-in form", () => {
  test("accepts the forms people type, like core.otp.normalize_phone", () => {
    for (const raw of ["09121234567", "9121234567", "+989121234567", "00989121234567", "0912 123-4567", "۰۹۱۲۱۲۳۴۵۶۷"]) {
      expect(normalizePhone(raw)).toBe("+989121234567");
    }
  });

  test("refuses landlines, short numbers and junk", () => {
    for (const raw of ["", "02112345678", "091212345", "+44 7700 900123", "abc", null, undefined]) {
      expect(normalizePhone(raw)).toBeNull();
    }
  });

  test("code is six digits, Persian digits folded", () => {
    expect(cleanCode("۱۲۳۴۵۶")).toBe("123456");
    expect(cleanCode("12345")).toBeNull();
    expect(cleanCode("12a456")).toBeNull();
    expect(displayPhone("+989121234567")).toBe("0912 123 4567");
  });

  test("resend countdown runs from 60 s to 0", () => {
    expect(resendIn(null)).toBe(0);
    expect(resendIn(1_000_000, 1_000_000)).toBe(60);
    expect(resendIn(1_000_000, 1_000_000 + 59_100)).toBe(1);
    expect(resendIn(1_000_000, 1_000_000 + 60_000)).toBe(0);
  });

  test("API refusals map to the web's wording, sms_unavailable included", async () => {
    mockFetch(() => ({ status: 503, body: { error: "sms_unavailable" } }));
    const error = await requestCode(BASE, "+989121234567").catch((err) => err);
    expect(error).toBeInstanceOf(ApiError);
    expect(otpReason(error)).toBe("sms_unavailable");
    expect(otpMessage(otpReason(error), "fa")).toBe("ورود با پیامک هنوز فعال نیست.");
    expect(otpMessage("sms_unavailable", "en")).toBe("SMS sign-in is not available yet.");
    expect(otpReason(new ApiError(429, "Request was throttled."))).toBe("throttled");
    expect(otpReason(new TypeError("Network request failed"))).toBe("network");
    expect(otpMessage("something_new", "en")).toBe("Sign-in failed. Try again.");
  });
});

describe("device registration", () => {
  beforeEach(() => AsyncStorage.clear());

  test("no provider keys: nothing is sent", async () => {
    const calls = mockFetch();
    expect(await syncDevice(BASE, "auth", null)).toBe(false);
    await forgetDevice(BASE, "auth");
    expect(calls).toHaveLength(0);
  });

  test("registers, re-registers on a token change after dropping the old one, unregisters on sign-out", async () => {
    const calls = mockFetch(() => ({ status: 201, body: { id: 1, kind: "fcm" } }));
    await syncDevice(BASE, "auth", { provider: "fcm", token: "t1" });
    expect(calls).toEqual([{ url: `${BASE}/api/account/devices/`, method: "POST", body: { kind: "fcm", token: "t1" }, auth: "Token auth" }]);

    // Same token on the next start: registered again (idempotent), nothing dropped.
    await syncDevice(BASE, "auth", { provider: "fcm", token: "t1" });
    expect(calls.map((call) => call.method)).toEqual(["POST", "POST"]);

    await syncDevice(BASE, "auth", { provider: "fcm", token: "t2" });
    expect(calls.slice(2)).toEqual([
      { url: `${BASE}/api/account/devices/`, method: "DELETE", body: { kind: "fcm", token: "t1" }, auth: "Token auth" },
      { url: `${BASE}/api/account/devices/`, method: "POST", body: { kind: "fcm", token: "t2" }, auth: "Token auth" },
    ]);

    await forgetDevice(BASE, "auth");
    expect(calls.at(-1)).toEqual({ url: `${BASE}/api/account/devices/`, method: "DELETE", body: { kind: "fcm", token: "t2" }, auth: "Token auth" });
    await forgetDevice(BASE, "auth");
    expect(calls).toHaveLength(5); // forgotten: a second sign-out sends nothing
  });

  test("a failed sign-out unregister never throws; a failed register does and is retried next start", async () => {
    mockFetch(() => ({ status: 500 }));
    await expect(syncDevice(BASE, "auth", { provider: "pushe", token: "p" })).rejects.toBeInstanceOf(ApiError);
    await expect(forgetDevice(BASE, "auth")).resolves.toBeUndefined();
  });
});

describe("watchlist", () => {
  const event = (id: number, slugs: string[] = []) => ({ id, watch_items: slugs.map((slug) => ({ slug, kind: "asset", name_fa: slug, name_en: slug })) });

  test("boost matches the web: marked, lifted a bounded number of places", () => {
    const events = Array.from({ length: 10 }, (_, index) => event(index, index === 7 ? ["usd_irr"] : []));
    const boosted = boostWatched(events, ["usd_irr"]);
    expect(boosted.findIndex((row) => row.id === 7)).toBe(7 - WATCH_BOOST);
    expect(boosted[0].id).toBe(0);
    expect(boosted.filter((row) => row.watched).map((row) => row.id)).toEqual([7]);
    expect(boostWatched(events, ["usd_irr"], { boost: false }).map((row) => row.id)).toEqual(events.map((row) => row.id));
    expect(boostWatched(events, null).map((row) => row.id)).toEqual(events.map((row) => row.id));
  });

  test("quiet hours and the item filter", () => {
    expect(cleanTime("7:05")).toBe("07:05");
    expect(cleanTime("۲۳:۰۰")).toBe("23:00");
    expect(cleanTime("24:00")).toBeNull();
    expect(cleanTime("7pm")).toBeNull();
    const items = [
      { slug: "usd", kind: "asset", name_fa: "دلار", name_en: "US dollar" },
      { slug: "cbi", kind: "actor", name_fa: "بانک مرکزی", name_en: "Central Bank" },
    ];
    expect(groupItems(items, "dollar").map(([kind, , , rows]) => [kind, rows.length])).toEqual([["asset", 1], ["actor", 0], ["theme", 0]]);
    expect(groupItems(items, "بانک")[1][3].map((item) => item.slug)).toEqual(["cbi"]);
  });
});
