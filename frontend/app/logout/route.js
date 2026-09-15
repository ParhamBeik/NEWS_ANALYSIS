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

export async function POST() {
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
  // A RELATIVE Location, deliberately.
  //
  // NextResponse.redirect() demands an absolute URL, and the only origin this handler can
  // see is the one Next bound to inside the container - so `new URL("/login", request.url)`
  // produced `https://0.0.0.0:3000/login` in production and sent every sign-out to an
  // address that does not exist. The edge does not rewrite Location, so nothing caught it.
  //
  // RFC 7231 allows Location to be a relative reference, which the browser resolves against
  // the URL it actually requested. That is right behind any proxy, needs no forwarded-host
  // parsing, and cannot drift from the edge configuration.
  return new NextResponse(null, { status: 303, headers: { Location: "/login" } });
}
