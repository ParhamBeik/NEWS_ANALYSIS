/**
 * Watchlist and alert-dial rules shared by onboarding and the watchlist screen. Labels match
 * the web (frontend/components/WatchPicker.js). Pure.
 */
import type { Dial, WatchItem } from "./api";

/** api.accounts.MIN_ONBOARDING_ITEMS: the server refuses onboarding below this. */
export const MIN_WATCH_ITEMS = 3;

export const KINDS: [string, string, string][] = [
  ["asset", "Assets", "دارایی‌ها"],
  ["actor", "Actors", "بازیگران و نهادها"],
  ["theme", "Themes", "موضوع‌ها"],
];

export const DIALS: [Dial, string, string, string, string][] = [
  ["low", "Low", "کم", "Tier 2 and above: more alerts", "اثر ۲ به بالا؛ هشدار بیشتر"],
  ["medium", "Medium", "متوسط", "Tier 3 and above", "اثر ۳ به بالا"],
  ["high", "High", "زیاد", "Tier 4 and above: only the big ones", "اثر ۴ به بالا؛ فقط خبرهای مهم"],
];

/** Items grouped by kind, filtered by a Persian or English needle. */
export function groupItems(items: WatchItem[], needle: string): [string, string, string, WatchItem[]][] {
  const query = needle.trim().toLowerCase();
  return KINDS.map(([kind, en, fa]) => [kind, en, fa, items.filter((item) => item.kind === kind
    && (!query || item.name_fa.includes(query) || item.name_en.toLowerCase().includes(query)))]);
}

/** "HH:MM" in 24 h, the form api.accounts.parse_time accepts; Persian digits allowed. Null when invalid. */
export function cleanTime(raw: string): string | null {
  const value = raw.trim().replace(/[۰-۹]/g, (digit) => String("۰۱۲۳۴۵۶۷۸۹".indexOf(digit)));
  const match = /^(\d{1,2}):(\d{2})$/.exec(value);
  if (!match) return null;
  const [hour, minute] = [Number(match[1]), Number(match[2])];
  return hour < 24 && minute < 60 ? `${String(hour).padStart(2, "0")}:${match[2]}` : null;
}
