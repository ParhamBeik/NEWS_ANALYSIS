import { cookies } from "next/headers";
import { NextResponse } from "next/server";

import { API_ORIGIN } from "@/lib/api";

/**
 * Sign out: revoke the token server-side, THEN drop the cookie.
 *
 * Deleting the cookie alone is not a sign-out. A DRF token never expires, so the string
 * the cookie held stays a valid credential for the entire corpus indefinitely - a token
 * captured from a shared machine or a proxy log would outlive every sign-out afterwards.
 *
 * The cookie is cleared regardless of what the API says. A revoke call that fails must not
 * leave the browser holding a session it believes it just ended; the user's next request
 * then either works with a token they thought was gone, or 401s into the login screen. The
 * second is recoverable, so failure closes.
 */

export async function POST(request) {
  const jar = await cookies();
  const token = jar.get("news_token")?.value;

  if (token) {
    try {
      await fetch(`${API_ORIGIN}/api/auth/logout/`, {
        method: "POST",
        headers: { Authorization: `Token ${token}` },
        cache: "no-store",
        signal: AbortSignal.timeout(10_000),
      });
    } catch {
      // The API being unreachable does not entitle the browser to keep the cookie.
    }
  }

  jar.delete("news_token");
  return NextResponse.redirect(new URL("/login", request.url), { status: 303 });
}
