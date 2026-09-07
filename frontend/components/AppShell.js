"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";

const NAV = [
  { href: "/", label: "Feed" },
  { href: "/ab", label: "A/B lab" },
  { href: "/review", label: "Review" },
  { href: "/kpi", label: "Quality" },
  { href: "/market", label: "Market" },
  { href: "/ops", label: "Ops" },
  { href: "/exports", label: "Exports" },
];

const AUTH_PATHS = ["/login", "/signup"];

export default function AppShell({ children }) {
  const pathname = usePathname();
  const isAuth = AUTH_PATHS.some((path) => pathname.startsWith(path));

  if (isAuth) {
    return <div className="min-h-screen bg-slate-950">{children}</div>;
  }

  return (
    <div className="min-h-screen bg-slate-950">
      <header className="sticky top-0 z-20 border-b border-slate-800 bg-slate-950/85 backdrop-blur">
        <div className="mx-auto flex max-w-7xl items-center gap-3 px-3 py-3 sm:gap-6 sm:px-5">
          <Link href="/" className="shrink-0 text-sm font-semibold tracking-tight text-slate-100">
            News<span className="text-emerald-400">Intel</span>
          </Link>
          <nav className="flex min-w-0 flex-1 flex-wrap gap-1 text-sm">
            {NAV.map((item) => (
              <Link
                key={item.href}
                href={item.href}
                className="rounded-md px-2 py-1 text-slate-400 transition hover:bg-slate-900 hover:text-slate-100"
              >
                {item.label}
              </Link>
            ))}
          </nav>
          <form action="/logout" method="post" className="shrink-0">
            <button className="text-xs text-slate-500 transition hover:text-slate-300">
              Sign out
            </button>
          </form>
        </div>
      </header>
      <main className="mx-auto max-w-7xl px-3 py-6 sm:px-5 sm:py-8">{children}</main>
    </div>
  );
}
