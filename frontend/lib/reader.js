/**
 * Reader presentation rules: tier labels, Jalali dates, Persian digits, category art and
 * source grouping. Pure functions with no Next.js imports, so tests load this file as-is.
 */

export const TIERS = [
  { level: 1, en: "Very low", fa: "خیلی کم" },
  { level: 2, en: "Low", fa: "کم" },
  { level: 3, en: "Medium", fa: "متوسط" },
  { level: 4, en: "High", fa: "زیاد" },
  { level: 5, en: "Very high", fa: "خیلی زیاد" },
];

/** Labels for the API's tier 1-5 (core/tiers.py decides it; the reader never does).
 *  A missing tier stays null - "not assessed" is never shown as "very low". */
export function tierMeta(level) {
  const value = Number(level);
  if (level === null || level === undefined || !Number.isInteger(value)) return null;
  return TIERS[value - 1] || null;
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

/** The eight investor topics (core.vocabulary.EVENT_CATEGORIES); the API maps legacy slugs. */
export const CATEGORIES = {
  conflict_security: { en: "Conflict & security", fa: "امنیت و درگیری", icon: "shield" },
  sanctions_diplomacy: { en: "Sanctions & diplomacy", fa: "تحریم و دیپلماسی", icon: "globe" },
  macro_monetary: { en: "Macro & monetary", fa: "اقتصاد کلان و پولی", icon: "bank" },
  energy_commodities: { en: "Energy & commodities", fa: "انرژی و کالاها", icon: "flame" },
  iran_economy_policy: { en: "Iran economic policy", fa: "سیاست اقتصادی ایران", icon: "chart" },
  markets_companies: { en: "Markets & companies", fa: "بازارها و شرکت‌ها", icon: "candles" },
  disasters: { en: "Disasters & accidents", fa: "حوادث و بلایا", icon: "wave" },
  social_unrest: { en: "Protests & strikes", fa: "اعتراض و اعتصاب", icon: "people" },
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

/** How independently the occurrence is reported (core.events.evidence_level). */
export const EVIDENCE = {
  single: { en: "One source group", fa: "یک گروه منبع" },
  multi: { en: "Independent sources", fa: "منابع مستقل" },
  official: { en: "Official source", fa: "منبع رسمی" },
  disputed: { en: "Sources disagree", fa: "روایت‌های متناقض" },
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
