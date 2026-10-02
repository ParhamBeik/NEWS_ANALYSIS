import AsyncStorage from "@react-native-async-storage/async-storage";
import { eventKey, isFresh, load, MAX_AGE_MS, prune, RADAR_KEY, save } from "../src/lib/cache";
import { faDigits, formatGregorian, formatJalali, toJalali } from "../src/lib/jalali";
import { absoluteUrl, impactScore, impactTier } from "../src/lib/reader";
import { gestureAction } from "../src/lib/swipe";
import { registerForPush, type PushProvider } from "../src/push/registry";

jest.mock("@react-native-async-storage/async-storage", () =>
  require("@react-native-async-storage/async-storage/jest/async-storage-mock"));

describe("jalali", () => {
  test("Nowruz and the leap Esfand", () => {
    expect(toJalali(2026, 3, 21)).toEqual([1405, 1, 1]);
    expect(toJalali(2025, 3, 20)).toEqual([1403, 12, 30]); // 1403 is a leap year
    expect(toJalali(2025, 3, 21)).toEqual([1404, 1, 1]);
    expect(toJalali(2026, 10, 2)).toEqual([1405, 7, 10]);
  });

  test("formats in Tehran time with Persian digits", () => {
    // 21:00 UTC is 00:30 next day in Tehran (+03:30).
    expect(formatJalali("2026-10-01T21:00:00Z", "fa")).toBe("۱۰ مهر ۱۴۰۵، ۰۰:۳۰");
    expect(formatJalali("2026-10-01T21:00:00Z", "en")).toBe("10 Mehr 1405, 00:30");
    expect(formatJalali("2026-10-01T21:00:00Z", "en", { time: false })).toBe("10 Mehr 1405");
    expect(formatGregorian("2026-10-01T21:00:00Z")).toBe("2 Oct 2026");
  });

  test("missing or invalid dates", () => {
    expect(formatJalali(null)).toBe("—");
    expect(formatJalali("not a date")).toBe("—");
    expect(faDigits("12:05")).toBe("۱۲:۰۵");
  });
});

describe("tiers", () => {
  test("20-point bands, unassessed stays null", () => {
    expect(impactTier(null)).toBeNull();
    expect(impactTier(0)?.level).toBe(1);
    expect(impactTier(79)?.level).toBe(4);
    expect(impactTier(80)?.level).toBe(5);
    expect(impactTier(100)?.level).toBe(5);
  });

  test("Iran/global weighting matches the API", () => {
    expect(impactScore({ iran_score: 80, global_score: 30 })).toBe(60);
    expect(impactScore({ iran_score: null, global_score: 30 })).toBe(30);
    expect(impactScore({ iran_score: null, global_score: null })).toBeNull();
  });

  test("relative media paths resolve against the server", () => {
    expect(absoluteUrl("/media/a.webp", "https://news.parhambm.ir/")).toBe("https://news.parhambm.ir/media/a.webp");
    expect(absoluteUrl("https://cdn.example/a.webp", "https://x")).toBe("https://cdn.example/a.webp");
    expect(absoluteUrl(null, "https://x")).toBeNull();
  });

  test("swipe needs a long, mostly horizontal drag", () => {
    expect(gestureAction(120, 10)).toBe("agree");
    expect(gestureAction(-120, 10)).toBe("fix");
    expect(gestureAction(40, 0)).toBeNull();
    expect(gestureAction(100, 150)).toBeNull();
  });
});

describe("offline cache", () => {
  const now = Date.UTC(2026, 9, 2, 12);
  beforeEach(() => AsyncStorage.clear());

  test("freshness window is 48 hours", () => {
    expect(isFresh(now - MAX_AGE_MS, now)).toBe(true);
    expect(isFresh(now - MAX_AGE_MS - 1, now)).toBe(false);
    expect(isFresh(now + 3600_000, now)).toBe(false); // clock moved back
  });

  test("round-trips and expires entries", async () => {
    await save(RADAR_KEY, [{ id: 1 }], now);
    expect(await load(RADAR_KEY, now + 1000)).toEqual({ savedAt: now, data: [{ id: 1 }] });
    expect(await load(RADAR_KEY, now + MAX_AGE_MS + 1)).toBeNull();
    expect(await AsyncStorage.getItem("ni:cache:radar")).toBeNull(); // stale row removed
  });

  test("prune drops stale and corrupt rows only", async () => {
    await save(eventKey(1), { id: 1 }, now - MAX_AGE_MS - 1);
    await save(eventKey(2), { id: 2 }, now);
    await AsyncStorage.setItem("ni:cache:event:3", "{broken");
    await AsyncStorage.setItem("ni:settings", "{}");
    expect(await prune(now)).toBe(2);
    expect(await load(eventKey(2), now)).not.toBeNull();
    expect(await AsyncStorage.getItem("ni:settings")).toBe("{}");
  });
});

describe("push registry", () => {
  const provider = (name: PushProvider["name"], configured: boolean, token: string | null | Error): PushProvider => ({
    name,
    isConfigured: () => configured,
    register: jest.fn(async () => { if (token instanceof Error) throw token; return token; }),
  });

  test("no-op when no provider is configured", async () => {
    const fcm = provider("fcm", false, "t");
    expect(await registerForPush({}, { fcm })).toBeNull();
    expect(fcm.register).not.toHaveBeenCalled();
  });

  test("falls back in order when a provider fails", async () => {
    const providers = { fcm: provider("fcm", true, new Error("no play services")), pushe: provider("pushe", true, "p-1") };
    expect(await registerForPush({}, providers)).toEqual({ provider: "pushe", token: "p-1" });
  });
});
