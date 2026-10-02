/**
 * Calls to the Django API. The radar endpoints are anonymous; reader accounts (phone sign-in)
 * and staff review use the same DRF token the web login issues, sent as `Authorization: Token`.
 */
import type { ReaderEvent } from "./reader";

export class ApiError extends Error {
  /** `code` is the API's stable refusal (`{"error": "sms_unavailable"}`), when it sent one. */
  constructor(public status: number, message: string, public code: string | null = null) {
    super(message);
  }
}

type Options = { token?: string | null; method?: "GET" | "POST" | "PUT" | "PATCH" | "DELETE"; body?: unknown };

async function request<T>(base: string, path: string, { token, method = "GET", body }: Options = {}): Promise<T> {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), 15_000);
  try {
    const response = await fetch(`${base.replace(/\/+$/, "")}${path}`, {
      method,
      signal: controller.signal,
      headers: {
        Accept: "application/json",
        ...(body !== undefined ? { "Content-Type": "application/json" } : {}),
        ...(token ? { Authorization: `Token ${token}` } : {}),
      },
      body: body !== undefined ? JSON.stringify(body) : undefined,
    });
    if (!response.ok) {
      let detail = response.statusText;
      let code: string | null = null;
      try {
        const payload = await response.json();
        code = typeof payload.error === "string" ? payload.error : null;
        detail = payload.detail || payload.non_field_errors?.[0] || code || JSON.stringify(payload);
      } catch {
        // keep statusText
      }
      throw new ApiError(response.status, detail, code);
    }
    return (response.status === 204 ? null : await response.json()) as T;
  } finally {
    clearTimeout(timer);
  }
}

export type Radar = { results: ReaderEvent[]; as_of: string; ranked?: boolean };

/** Ranked last-24h radar; an empty window falls back to the newest reports, as on the web.
 *  `ranked` is false for that latest-first fallback, which the watchlist must not reorder. */
export async function fetchRadar(base: string): Promise<Radar> {
  const radar = await request<Radar>(base, "/api/public/events/?period=now&mode=ranked");
  if (radar.results.length) return { ...radar, ranked: true };
  return { ...(await request<Radar>(base, "/api/public/events/?period=latest&mode=latest")), ranked: false };
}

export const fetchEvent = (base: string, id: number | string) =>
  request<ReaderEvent>(base, `/api/public/events/${encodeURIComponent(String(id))}/`);

export const login = (base: string, username: string, password: string) =>
  request<{ token: string }>(base, "/api/auth/token/", { method: "POST", body: { username, password } });

export const me = (base: string, token: string) =>
  request<{ username: string; is_staff: boolean }>(base, "/api/auth/me/", { token });

export const logout = (base: string, token: string) =>
  request<null>(base, "/api/auth/logout/", { method: "POST", token, body: {} });

export type ReviewCard = ReaderEvent & {
  review_reason: string;
  skipped: boolean;
  iran_tier: number | null;
  global_tier: number | null;
};

export const reviewQueue = (base: string, token: string) =>
  request<{ pending: number; results: ReviewCard[] }>(base, "/api/review/queue/?limit=20", { token });

export type Decision =
  | { action: "agree" | "skip" | "undo" }
  | { action: "fix"; category: string; iran_tier: number; global_tier: number };

export const decide = (base: string, token: string, eventId: number, decision: Decision) =>
  request<unknown>(base, `/api/review/events/${eventId}/`, { method: "POST", token, body: decision });

// ------------------------------------------------------------------ reader accounts

export type WatchItem = { slug: string; kind: string; name_fa: string; name_en: string };
export type Dial = "low" | "medium" | "high";

export type Account = {
  phone: string | null;
  email: string;
  dial: Dial;
  quiet_start: string;
  quiet_end: string;
  email_digest: boolean;
  onboarded: boolean;
  watchlist: WatchItem[];
  unread: number;
};

/** Texts a sign-in code. Refusals arrive as ApiError.code: invalid_phone, too_soon, too_many,
 *  sms_unavailable (the server has no SMS provider keys yet). */
export const requestCode = (base: string, phone: string) =>
  request<{ sent: boolean }>(base, "/api/auth/otp/request/", { method: "POST", body: { phone } });

export const verifyCode = (base: string, phone: string, code: string) =>
  request<{ token: string; created: boolean; onboarded: boolean }>(base, "/api/auth/otp/verify/", {
    method: "POST", body: { phone, code },
  });

export const fetchAccount = (base: string, token: string) => request<Account>(base, "/api/account/", { token });

export type AccountChanges = Partial<Pick<Account, "dial" | "quiet_start" | "quiet_end">> & { onboarded?: boolean };

export const updateAccount = (base: string, token: string, changes: AccountChanges) =>
  request<Account>(base, "/api/account/", { method: "PATCH", token, body: changes });

/** Deletes the account now; the server cascades token, watchlist, devices and alerts. */
export const deleteAccount = (base: string, token: string) =>
  request<null>(base, "/api/account/", { method: "DELETE", token });

export const fetchWatchItems = (base: string) =>
  request<{ results: WatchItem[] }>(base, "/api/public/watch-items/");

export const saveWatchlist = (base: string, token: string, slugs: string[]) =>
  request<{ results: WatchItem[] }>(base, "/api/account/watchlist/", { method: "PUT", token, body: { slugs } });

export type DeviceKind = "fcm" | "pushe" | "najva";

export const registerDevice = (base: string, token: string, kind: DeviceKind, pushToken: string) =>
  request<{ id: number; kind: DeviceKind }>(base, "/api/account/devices/", { method: "POST", token, body: { kind, token: pushToken } });

export const unregisterDevice = (base: string, token: string, kind: DeviceKind, pushToken: string) =>
  request<null>(base, "/api/account/devices/", { method: "DELETE", token, body: { kind, token: pushToken } });

export type InboxRow = {
  id: number;
  kind: "new" | "update";
  tier: number | null;
  breaking: boolean;
  held: "quiet" | "cap" | null;
  created_at: string;
  read: boolean;
  event: { id: number; title: string; title_en: string | null; category: string | null };
};
export type Inbox = { unread: number; results: InboxRow[] };

export const fetchInbox = (base: string, token: string) => request<Inbox>(base, "/api/account/inbox/", { token });

export const markAllRead = (base: string, token: string) =>
  request<{ marked: number }>(base, "/api/account/inbox/read/", { method: "POST", token, body: { all: true } });
