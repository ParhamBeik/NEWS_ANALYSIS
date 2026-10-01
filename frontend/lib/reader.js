/**
 * Reader presentation rules: impact tiers, Jalali dates, Persian digits, category art and
 * source grouping. Pure functions with no Next.js imports, so tests load this file as-is.
 */

export const TIERS = [
  { level: 1, en: "Very low", fa: "خیلی کم" },
  { level: 2, en: "Low", fa: "کم" },
  { level: 3, en: "Medium", fa: "متوسط" },
  { level: 4, en: "High", fa: "زیاد" },
  { level: 5, en: "Very high", fa: "خیلی زیاد" },
];

/** 0-100 score to tier 1-5 in equal 20-point bands; 80+ matches the alert threshold.
 *  A missing score stays null - "not assessed" is never shown as "very low". */
export function impactTier(score) {
  if (score === null || score === undefined || score === "") return null;
  const value = Number(score);
  if (!Number.isFinite(value)) return null;
  return TIERS[Math.min(4, Math.max(0, Math.floor(value / 20)))];
}

/** The same Iran/global weighting the API ranks by (core.events.ranked_events). */
export function impactScore(event) {
  const iran = event?.iran_score;
  const global = event?.global_score;
  if (iran == null && global == null) return null;
  if (iran == null) return global;
  if (global == null) return iran;
  return Math.round(0.6 * iran + 0.4 * global);
}

const TEHRAN = "Asia/Tehran";

/** List separator. A middle dot beside Persian digits reads as a zero (۰), so Persian uses a comma. */
export function sep(lang) {
  return lang === "fa" ? "، " : " · ";
}

export function digits(value, lang) {
  if (value === null || value === undefined) return "—";
  return lang === "fa" ? Number(value).toLocaleString("fa-IR") : Number(value).toLocaleString("en-US");
}

/** Jalali calendar in both languages, Tehran wall-clock. `time: false` drops the clock. */
export function jalali(iso, lang = "fa", { time = true } = {}) {
  if (!iso) return "—";
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return "—";
  const locale = lang === "fa" ? "fa-IR-u-ca-persian-nu-arabext" : "en-US-u-ca-persian-nu-latn";
  const parts = Object.fromEntries(
    new Intl.DateTimeFormat(locale, {
      timeZone: TEHRAN, day: "numeric", month: "long", year: "numeric",
      hour: "2-digit", minute: "2-digit", hourCycle: "h23",
    }).formatToParts(date).map((part) => [part.type, part.value]),
  );
  const day = `${parts.day} ${parts.month} ${parts.year}`;
  return time ? `${day}${lang === "fa" ? "، " : ", "}${parts.hour}:${parts.minute}` : day;
}

/** Gregorian equivalent for the `title` attribute. */
export function gregorian(iso) {
  if (!iso) return "";
  return new Date(iso).toLocaleString("en-GB", {
    timeZone: TEHRAN, day: "numeric", month: "short", year: "numeric",
    hour: "2-digit", minute: "2-digit", timeZoneName: "short",
  });
}

const UNITS = [["year", 31536000], ["month", 2592000], ["week", 604800], ["day", 86400], ["hour", 3600], ["minute", 60]];

export function relative(iso, lang = "fa", now = Date.now()) {
  if (!iso) return "";
  const seconds = (new Date(iso).getTime() - now) / 1000;
  const format = new Intl.RelativeTimeFormat(lang === "fa" ? "fa" : "en", { numeric: "auto" });
  for (const [unit, size] of UNITS) {
    if (Math.abs(seconds) >= size) return format.format(Math.round(seconds / size), unit);
  }
  return lang === "fa" ? "همین حالا" : "just now";
}

export const CATEGORIES = {
  monetary: { en: "Monetary policy", fa: "سیاست پولی", icon: "bank" },
  macro: { en: "Macroeconomy", fa: "اقتصاد کلان", icon: "chart" },
  sanctions_trade: { en: "Trade & sanctions", fa: "تجارت و تحریم", icon: "ship" },
  geopolitics: { en: "Geopolitics", fa: "ژئوپلیتیک", icon: "globe" },
  energy: { en: "Energy", fa: "انرژی", icon: "flame" },
  markets: { en: "Markets", fa: "بازارها", icon: "candles" },
};
export const PENDING_CATEGORY = { en: "Being assessed", fa: "در حال ارزیابی", icon: "radar" };

export function categoryOf(event) {
  return CATEGORIES[event?.category] || PENDING_CATEGORY;
}

/** Sections in the order their best-ranked event appears; input order is preserved. */
export function groupByCategory(events) {
  const groups = new Map();
  for (const event of events) {
    const key = CATEGORIES[event.category] ? event.category : "pending";
    if (!groups.has(key)) groups.set(key, []);
    groups.get(key).push(event);
  }
  return [...groups].map(([key, items]) => ({ key, items }));
}

export function headline(event, lang) {
  return (lang === "fa" ? event.title_fa : event.title_en) || event.original_title || event.title || "";
}

/** One line on why it may matter: the impact channels when written, else the brief. */
export function whyItMatters(event, lang) {
  return lang === "fa" ? (event.channels_fa || event.brief_fa) : (event.channels_en || event.brief_en);
}

export const STATUS = {
  developing: { en: "Developing", fa: "در حال تکمیل", tone: "pending" },
  assessed: { en: "Assessed", fa: "ارزیابی‌شده", tone: "solid" },
  corrected: { en: "Corrected", fa: "اصلاح‌شده", tone: "solid" },
  withdrawn: { en: "Withdrawn", fa: "پس‌گرفته‌شده", tone: "alert" },
};

export function sourceCount(event) {
  return new Set((event.sources || []).map((source) => source.original_outlet || source.name)).size;
}

/**
 * Sources grouped for the event page.
 * TODO(reader): group by independence (official / state / private / international) once
 * Source carries that metadata; the API exposes only a display name today.
 */
export function groupSources(sources = []) {
  const groups = new Map();
  for (const source of sources) {
    const name = source.original_outlet || source.name;
    if (!groups.has(name)) groups.set(name, []);
    groups.get(name).push(source);
  }
  return [...groups]
    .map(([name, items]) => ({ name, items }))
    .sort((a, b) => b.items.length - a.items.length || a.name.localeCompare(b.name));
}

export const RANGE_DAYS = { "1W": 7, "1M": 30, "3M": 90, "1Y": 365 };

/** Smallest timeline window that still shows some price history before the event. */
export function rangeFor(eventIso, now = Date.now()) {
  const age = (now - new Date(eventIso).getTime()) / 86400000;
  return Object.entries(RANGE_DAYS).find(([, days]) => age <= days * 0.7)?.[0] || "1Y";
}

/** Assets ordered by the event's assessed relevance to their class; all assets if unassessed. */
export function linkedAssets(assetScores = {}, catalog = []) {
  const scored = catalog.filter((asset) => assetScores?.[asset.class] != null);
  if (!scored.length) return catalog;
  return [...scored].sort((a, b) => assetScores[b.class] - assetScores[a.class]);
}

/** Price series to SVG coordinates. Returns null when there is nothing to draw. */
export function chartGeometry(points, { start, end, width, height, pad = 0 }) {
  const rows = points
    .map((point) => [new Date(point.observed_at).getTime(), Number(point.price)])
    .filter(([time, price]) => Number.isFinite(time) && Number.isFinite(price));
  if (!rows.length) return null;
  let low = Math.min(...rows.map(([, price]) => price));
  let high = Math.max(...rows.map(([, price]) => price));
  if (low === high) { low -= 1; high += 1; }
  const x = (time) => ((time - start) / (end - start)) * width;
  const y = (price) => pad + (1 - (price - low) / (high - low)) * (height - 2 * pad);
  const path = rows.map(([time, price], index) => `${index ? "L" : "M"}${x(time).toFixed(1)},${y(price).toFixed(1)}`).join(" ");
  return { path, low, high, x, y, first: rows[0], last: rows.at(-1) };
}
