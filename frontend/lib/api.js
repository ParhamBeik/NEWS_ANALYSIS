import { cookies } from "next/headers";
import { redirect } from "next/navigation";

/**
 * Server-side access to the Django API.
 *
 * The token lives in an httpOnly cookie and is attached here, on the server. Two reasons
 * it is not held in the browser:
 *
 *   - httpOnly means no script on the page can read it, so an injected script cannot
 *     exfiltrate a credential that grants the whole corpus.
 *   - Server components cannot see browser cookies on an outbound fetch anyway, so a
 *     session-cookie design would force every page to be a client component and give up
 *     server rendering entirely.
 *
 * `no-store` on every call: this is an operational dashboard. A cached /ops that shows a
 * budget figure from ten minutes ago is worse than a slow one.
 */

const API_ORIGIN = process.env.API_ORIGIN || "http://127.0.0.1:8000";

export async function apiFetch(path, options = {}) {
  const token = (await cookies()).get("news_token")?.value;
  const response = await fetch(`${API_ORIGIN}${path}`, {
    ...options,
    cache: "no-store",
    headers: {
      "Content-Type": "application/json",
      ...(token ? { Authorization: `Token ${token}` } : {}),
      ...options.headers,
    },
  });
  return response;
}

/** Fetch JSON, sending an expired or missing session back to the login screen. */
export async function apiGet(path) {
  const response = await apiFetch(path);
  if (response.status === 401 || response.status === 403) redirect("/login");
  if (response.status === 204) return null;
  if (!response.ok) {
    throw new Error(`${path} failed: ${response.status} ${await response.text()}`);
  }
  return response.json();
}

export async function apiPost(path, body) {
  const response = await apiFetch(path, { method: "POST", body: JSON.stringify(body) });
  if (response.status === 401 || response.status === 403) redirect("/login");
  if (!response.ok) {
    throw new Error(`${path} failed: ${response.status} ${await response.text()}`);
  }
  return response.status === 204 ? null : response.json();
}

/** Turn a params object into a query string, dropping empty values rather than sending
 *  `?source=` - which django-filter would treat as a real filter on the empty string. */
export function query(params) {
  const search = new URLSearchParams();
  for (const [key, value] of Object.entries(params)) {
    if (value !== undefined && value !== null && value !== "") search.set(key, value);
  }
  const encoded = search.toString();
  return encoded ? `?${encoded}` : "";
}
