/**
 * Offline cache: the last radar and every opened event, each kept for 48 hours.
 *
 * Entries carry their own save time so the app can say "last synced" and drop stale rows;
 * nothing older than MAX_AGE_MS is ever shown as current news.
 */
import AsyncStorage from "@react-native-async-storage/async-storage";

export const MAX_AGE_MS = 48 * 3600 * 1000;
const PREFIX = "ni:cache:";
export const RADAR_KEY = "radar";
export const eventKey = (id: number | string) => `event:${id}`;

export type Entry<T> = { savedAt: number; data: T };

/** Fresh = saved within the window and not in the future (a clock moved back counts as stale). */
export function isFresh(savedAt: number, now = Date.now(), maxAge = MAX_AGE_MS): boolean {
  return Number.isFinite(savedAt) && savedAt <= now + 60_000 && now - savedAt <= maxAge;
}

export async function save<T>(key: string, data: T, now = Date.now()): Promise<void> {
  await AsyncStorage.setItem(PREFIX + key, JSON.stringify({ savedAt: now, data }));
}

/** The cached entry, or null when absent, unreadable or stale (stale rows are removed). */
export async function load<T>(key: string, now = Date.now()): Promise<Entry<T> | null> {
  const raw = await AsyncStorage.getItem(PREFIX + key);
  if (!raw) return null;
  try {
    const entry = JSON.parse(raw) as Entry<T>;
    if (isFresh(entry.savedAt, now)) return entry;
  } catch {
    // fall through: a corrupt row is as good as a stale one
  }
  await AsyncStorage.removeItem(PREFIX + key);
  return null;
}

/** Remove every stale or corrupt cache row. Returns how many were removed. */
export async function prune(now = Date.now()): Promise<number> {
  const keys = (await AsyncStorage.getAllKeys()).filter((key) => key.startsWith(PREFIX));
  const rows = await AsyncStorage.multiGet(keys);
  const stale = rows
    .filter(([, raw]) => {
      try {
        return !isFresh((JSON.parse(raw ?? "") as Entry<unknown>).savedAt, now);
      } catch {
        return true;
      }
    })
    .map(([key]) => key);
  if (stale.length) await AsyncStorage.multiRemove(stale);
  return stale.length;
}
