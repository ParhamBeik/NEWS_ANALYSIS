import { NextResponse } from "next/server";

/**
 * The whole site is behind login.
 *
 * This is a fail-closed gate: it redirects unless the request is for the login screen or a
 * static asset. Listing what is PUBLIC rather than what is protected means a page added
 * later is protected by default - the opposite ordering leaks every new page until someone
 * remembers to add it.
 *
 * The cookie's presence is all that is checked here. Middleware runs on the edge runtime
 * with no database, so it cannot validate the token; the API rejects a stale one and
 * `apiGet` redirects back to /login. This gate exists to avoid rendering a shell that is
 * about to 403, not to be the security boundary. The security boundary is Django.
 */

const PUBLIC = ["/login", "/signup", "/_next", "/favicon.ico"];

function withPathname(request, pathname) {
  const requestHeaders = new Headers(request.headers);
  requestHeaders.set("x-pathname", pathname);
  return NextResponse.next({ request: { headers: requestHeaders } });
}

export function middleware(request) {
  const { pathname } = request.nextUrl;
  const hasToken = Boolean(request.cookies.get("news_token"));

  if (PUBLIC.some((prefix) => pathname.startsWith(prefix))) {
    // A revoked token still has a cookie. Redirecting it home loops back here on the API 401.
    return withPathname(request, pathname);
  }

  if (hasToken) return withPathname(request, pathname);

  const target = request.nextUrl.clone();
  target.pathname = "/login";
  target.search = pathname === "/" ? "" : `?next=${encodeURIComponent(pathname)}`;
  return NextResponse.redirect(target);
}

export const config = {
  matcher: ["/((?!_next/static|_next/image).*)"],
};
