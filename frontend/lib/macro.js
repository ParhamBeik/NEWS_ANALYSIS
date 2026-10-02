import { digits } from "./reader.js";

/**
 * Central-bank meeting calendar for the macro page. Static on purpose: these are published
 * a year ahead and change rarely. Dates are the decision day (the last day of a two-day
 * meeting). Check against the source links before each new year and add the next one.
 * `rate` is the policy rate after the latest decision, or null until someone records it.
 * The CBI publishes no fixed schedule, so it has no dates; the page says so.
 */
export const POLICY_CALENDAR = [
  {
    key: "fomc", name_fa: "فدرال رزرو آمریکا", name_en: "US Federal Reserve (FOMC)",
    source: "https://www.federalreserve.gov/monetarypolicy/fomccalendars.htm",
    rate: null,
    dates: ["2026-01-28", "2026-03-18", "2026-04-29", "2026-06-17", "2026-07-29", "2026-09-16", "2026-10-28", "2026-12-09"],
  },
  {
    key: "ecb", name_fa: "بانک مرکزی اروپا", name_en: "European Central Bank",
    source: "https://www.ecb.europa.eu/press/calendars/mgcgc/html/index.en.html",
    rate: null,
    dates: ["2026-02-05", "2026-03-19", "2026-04-30", "2026-06-11", "2026-07-23", "2026-09-10", "2026-10-29", "2026-12-17"],
  },
  {
    key: "cbi", name_fa: "بانک مرکزی ایران", name_en: "Central Bank of Iran",
    source: "https://www.cbi.ir/",
    rate: null,
    dates: [],
  },
];

/** The next decision on or after `now`, plus whole days until it; null when none is listed. */
export function nextMeeting(bank, now = Date.now()) {
  const today = new Date(now).toISOString().slice(0, 10);
  const date = bank.dates.find((day) => day >= today);
  if (!date) return null;
  const days = Math.round((Date.parse(`${date}T00:00:00Z`) - Date.parse(`${today}T00:00:00Z`)) / 86400000);
  return { date, days };
}

/** Rial series display in toman (÷10), which is how readers quote prices. */
export function displayPrice(value, unit, lang) {
  if (value === null || value === undefined || value === "") return { text: "—", unit: "" };
  let number = Number(value);
  let shown = unit;
  if (unit === "IRR") {
    number /= 10;
    shown = lang === "fa" ? "تومان" : "toman";
  }
  const rounded = Math.abs(number) >= 1000 ? Math.round(number) : Math.round(number * 100) / 100;
  return { text: digits(rounded, lang), unit: shown };
}

/** Direction glyph only. Colour stays neutral: a move is not good or bad news by itself. */
export function direction(changePct) {
  const value = Number(changePct);
  if (changePct === null || changePct === undefined || !Number.isFinite(value) || value === 0) return "→";
  return value > 0 ? "▲" : "▼";
}

/** Polyline path for a sparkline; null when fewer than two numbers. */
export function sparkPath(values, width = 100, height = 28) {
  const rows = (values || []).map(Number).filter(Number.isFinite);
  if (rows.length < 2) return null;
  let low = Math.min(...rows);
  let high = Math.max(...rows);
  if (low === high) { low -= 1; high += 1; }
  const step = width / (rows.length - 1);
  return rows.map((value, index) => `${index ? "L" : "M"}${(index * step).toFixed(1)},${((1 - (value - low) / (high - low)) * height).toFixed(1)}`).join(" ");
}
