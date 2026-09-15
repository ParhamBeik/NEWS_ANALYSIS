import { cookies, headers } from "next/headers";
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

/**
 * Where Django lives, declared once.
 *
 * The fallback is the local `manage.py runserver` address; in every deployed environment
 * compose sets API_ORIGIN to the internal hostname. It is exported because the two routes
 * that deliberately bypass `apiGet` - sign-in, which runs before a token exists, and
 * sign-out, which must not redirect on failure - still have to reach the same server. They
 * import the constant, not the client, so they keep their own fetch semantics.
 */
export const API_ORIGIN = process.env.API_ORIGIN || "http://127.0.0.1:8000";

export class ApiError extends Error {
  constructor(path, status, detail = "") {
    super(`${path} failed: ${status}${detail ? ` ${detail}` : ""}`);
    this.name = "ApiError";
    this.path = path;
    this.status = status;
  }
}

async function loginRedirect() {
  const pathname = (await headers()).get("x-pathname");
  if (pathname && pathname !== "/login" && pathname !== "/signup") {
    redirect(`/login?next=${encodeURIComponent(pathname)}`);
  }
  redirect("/login");
}

export async function apiFetch(path, options = {}) {
  const token = (await cookies()).get("news_token")?.value;
  const response = await fetch(`${API_ORIGIN}${path}`, {
    ...options,
    cache: "no-store",
    signal: options.signal ?? AbortSignal.timeout(15_000),
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
  if (response.status === 401) await loginRedirect();
  if (response.status === 204) return null;
  if (!response.ok) {
    throw new ApiError(path, response.status, await response.text());
  }
  return response.json();
}

export async function apiPost(path, body) {
  const response = await apiFetch(path, { method: "POST", body: JSON.stringify(body) });
  if (response.status === 401) await loginRedirect();
  if (!response.ok) {
    throw new Error(`${path} failed: ${response.status} ${await response.text()}`);
  }
  return response.status === 204 ? null : response.json();
}

/**
 * Who is signed in, or null.
 *
 * Deliberately not built on `apiGet`: this runs in the root layout, which also renders
 * /login and /signup. `apiGet` redirects to /login on a 401, and redirecting to a page
 * whose own layout issues the same redirect is an infinite loop. A signed-out visitor is
 * the normal case here, not an error, so every failure - no cookie, revoked token, API
 * down - collapses to null and the shell renders without a name.
 */
export async function currentUser() {
  if (!(await cookies()).get("news_token")) return null;
  try {
    const response = await apiFetch("/api/auth/me/");
    if (!response.ok) return null;
    const { username, is_staff: isStaff } = await response.json();
    return { username, isStaff: Boolean(isStaff) };
  } catch {
    return null;
  }
}

/** Return the signed-in operator when a server-rendered route is staff-only. */
export async function currentStaffUser() {
  const user = await currentUser();
  if (!user) await loginRedirect();
  return user?.isStaff ? user : null;
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
