/**
 * Reader presentation rules, mirrored from frontend/lib/reader.js so web and app show the
 * same tier for the same score. Pure: no React Native imports.
 */
import type { Lang } from "./jalali";

export type Source = {
  name: string;
  original_outlet: string | null;
  url: string;
  published_at: string | null;
  first_seen_at: string | null;
  date_uncertain?: boolean;
  headline?: string;
  lead?: string;
};

export type ReaderEvent = {
  id: number;
  status: string;
  category: string | null;
  title: string;
  title_fa: string | null;
  title_en: string | null;
  original_title: string;
  brief_fa: string | null;
  brief_en: string | null;
  channels_fa: string | null;
  channels_en: string | null;
  uncertainty_fa: string | null;
  uncertainty_en: string | null;
  iran_score: number | null;
  global_score: number | null;
  event_time: string | null;
  first_seen_at: string | null;
  image_url: string | null;
  image_large_url: string | null;
  sources: Source[];
  watch_items?: { slug: string; kind: string; name_fa: string; name_en: string }[];
  /** Set by boostWatched: the event touches the reader's watchlist. */
  watched?: boolean;
};

/** How many places an event on the reader's watchlist moves up the ranked radar. */
export const WATCH_BOOST = 5;

/**
 * Mark events that touch the reader's watchlist and lift each one WATCH_BOOST places.
 * A bounded lift, not a sort to the top: a minor watched story must not bury a tier-5 one.
 * With `boost: false` (latest-first order) events are only marked.
 * Ported from frontend/lib/reader.js boostWatched; keep the two in step.
 */
export function boostWatched<T extends Pick<ReaderEvent, "watch_items">>(
  events: T[], slugs: string[] | null | undefined, { boost = true } = {},
): (T & { watched: boolean })[] {
  const watched = new Set(slugs || []);
  const marked = events.map((event, index) => ({
    event: { ...event, watched: (event.watch_items || []).some((item) => watched.has(item.slug)) },
    rank: index,
  }));
  if (boost) for (const row of marked) if (row.event.watched) row.rank -= WATCH_BOOST + 0.5;
  return marked.sort((a, b) => a.rank - b.rank).map((row) => row.event);
}

export const TIERS = [
  { level: 1, en: "Very low", fa: "خیلی کم" },
  { level: 2, en: "Low", fa: "کم" },
  { level: 3, en: "Medium", fa: "متوسط" },
  { level: 4, en: "High", fa: "زیاد" },
  { level: 5, en: "Very high", fa: "خیلی زیاد" },
] as const;
export type Tier = (typeof TIERS)[number];

/** 0-100 score to tier 1-5 in equal 20-point bands. A missing score stays null: "not
 *  assessed" is never shown as "very low". */
export function impactTier(score: number | null | undefined): Tier | null {
  if (score === null || score === undefined) return null;
  const value = Number(score);
  if (!Number.isFinite(value)) return null;
  return TIERS[Math.min(4, Math.max(0, Math.floor(value / 20)))];
}

/** Same Iran/global weighting the API ranks by (core.events.ranked_events). */
export function impactScore(event: Pick<ReaderEvent, "iran_score" | "global_score">): number | null {
  const { iran_score: iran, global_score: global } = event;
  if (iran == null && global == null) return null;
  if (iran == null) return global;
  if (global == null) return iran;
  return Math.round(0.6 * iran + 0.4 * global);
}

export const CATEGORIES: Record<string, { en: string; fa: string; color: string }> = {
  monetary: { en: "Monetary policy", fa: "سیاست پولی", color: "#0f5f59" },
  macro: { en: "Macroeconomy", fa: "اقتصاد کلان", color: "#075985" },
  sanctions_trade: { en: "Trade & sanctions", fa: "تجارت و تحریم", color: "#8a4b0f" },
  geopolitics: { en: "Geopolitics", fa: "ژئوپلیتیک", color: "#273449" },
  energy: { en: "Energy", fa: "انرژی", color: "#9a3412" },
  markets: { en: "Markets", fa: "بازارها", color: "#065f46" },
};
export const PENDING_CATEGORY = { en: "Being assessed", fa: "در حال ارزیابی", color: "#3a3d52" };

export function categoryOf(category: string | null | undefined) {
  return (category && CATEGORIES[category]) || PENDING_CATEGORY;
}

export function headline(event: ReaderEvent, lang: Lang): string {
  return (lang === "fa" ? event.title_fa : event.title_en) || event.original_title || event.title || "";
}

export function pick(event: ReaderEvent, field: "brief" | "channels" | "uncertainty", lang: Lang): string | null {
  return event[`${field}_${lang}`];
}

/** Media paths come back relative ("/media/..."); the app has no origin to resolve them against. */
export function absoluteUrl(url: string | null | undefined, base: string): string | null {
  if (!url) return null;
  if (/^https?:\/\//.test(url)) return url;
  return `${base.replace(/\/+$/, "")}/${url.replace(/^\/+/, "")}`;
}
