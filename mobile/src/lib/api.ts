/**
 * Calls to the Django API. The reader endpoints are anonymous; staff review uses the same
 * DRF token the web login issues (POST /api/auth/token/), sent as `Authorization: Token`.
 */
import type { ReaderEvent } from "./reader";

export class ApiError extends Error {
  constructor(public status: number, message: string) {
    super(message);
  }
}

type Options = { token?: string | null; method?: "GET" | "POST"; body?: unknown };

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
      try {
        const payload = await response.json();
        detail = payload.detail || payload.non_field_errors?.[0] || JSON.stringify(payload);
      } catch {
        // keep statusText
      }
      throw new ApiError(response.status, detail);
    }
    return (response.status === 204 ? null : await response.json()) as T;
  } finally {
    clearTimeout(timer);
  }
}

export type Radar = { results: ReaderEvent[]; as_of: string };

/** Ranked last-24h radar; an empty window falls back to the newest reports, as on the web. */
export async function fetchRadar(base: string): Promise<Radar> {
  const radar = await request<Radar>(base, "/api/public/events/?period=now&mode=ranked");
  return radar.results.length ? radar : request<Radar>(base, "/api/public/events/?period=latest&mode=latest");
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
