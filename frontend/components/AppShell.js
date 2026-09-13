"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";

const NAV = [
  { href: "/", label: "Feed" },
  { href: "/ab", label: "A/B lab", staffOnly: true },
  { href: "/review", label: "Review", staffOnly: true },
  { href: "/kpi", label: "Quality" },
  { href: "/market", label: "Market" },
  { href: "/ops", label: "Ops" },
  { href: "/exports", label: "Exports" },
];

const AUTH_PATHS = ["/login", "/signup"];

export default function AppShell({ children, user = null }) {
  const pathname = usePathname();
  const isAuth = AUTH_PATHS.some((path) => pathname.startsWith(path));

  if (isAuth) {
    return <div className="min-h-screen bg-slate-950">{children}</div>;
  }

  return (
    <div className="min-h-screen bg-slate-950">
      {/* Seven nav links sit above the content on every page. Without this, reaching the
          page itself costs eight tab presses after every single navigation. Visible only
          on focus, so it stays out of the way of everyone who does not need it. */}
      <a
        href="#main"
        className="sr-only focus:not-sr-only focus:absolute focus:left-3 focus:top-3 focus:z-50 focus:rounded-md focus:bg-emerald-500 focus:px-3 focus:py-2 focus:text-sm focus:font-medium focus:text-slate-950"
      >
        Skip to content
      </a>
      <header className="sticky top-0 z-20 border-b border-slate-800 bg-slate-950/85 backdrop-blur">
        <div className="mx-auto flex max-w-7xl items-center gap-3 px-3 py-3 sm:gap-6 sm:px-5">
          <Link href="/" className="shrink-0 text-sm font-semibold tracking-tight text-slate-100">
            News<span className="text-emerald-400">Intel</span>
          </Link>
          <nav aria-label="Main" className="flex min-w-0 flex-1 flex-wrap gap-1 text-sm">
            {NAV.filter((item) => !item.staffOnly || user?.isStaff).map((item) => {
              // Exact match for the feed, prefix match for everything else - otherwise "/"
              // is a prefix of every route and every tab renders as the current one.
              const active =
                item.href === "/" ? pathname === "/" : pathname.startsWith(item.href);
              return (
                <Link
                  key={item.href}
                  href={item.href}
                  // `aria-current` is what tells a screen reader which tab is the current
                  // page. The colour alone conveys it to sighted users only, and on a
                  // seven-item nav "where am I" is the question being answered.
                  aria-current={active ? "page" : undefined}
                  className={`rounded-md px-2 py-1 transition ${
                    active
                      ? "bg-slate-900 text-slate-100"
                      : "text-slate-400 hover:bg-slate-900 hover:text-slate-100"
                  }`}
                >
                  {item.label}
                </Link>
              );
            })}
          </nav>
          <div className="flex shrink-0 items-center gap-3">
            {/* Which account this window is signed in as. Two people on the same product
                look identical without it, and the sign-out button below reads as a threat
                to whoever cannot tell whose session they are about to end. */}
            {user ? (
              <span className="max-w-[12ch] truncate text-xs text-slate-400 sm:max-w-none">
                {user.username}
              </span>
            ) : null}
            {/* A plain anchor, not next/link: /admin/ is Django's, and a client-side
                navigation to it would 404 in the Next router before the request leaves. */}
            {user?.isStaff ? (
              <a
                href="/admin/"
                className="text-xs text-slate-500 transition hover:text-slate-300"
              >
                Admin
              </a>
            ) : null}
            <form action="/logout" method="post">
              <button
                type="submit"
                className="text-xs text-slate-500 transition hover:text-slate-300"
              >
                Sign out
              </button>
            </form>
          </div>
        </div>
      </header>
      <main id="main" tabIndex={-1} className="mx-auto max-w-7xl px-3 py-6 sm:px-5 sm:py-8">
        {children}
      </main>
    </div>
  );
}
