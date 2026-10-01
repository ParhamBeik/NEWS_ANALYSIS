"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";

const NAV = [
  { href: "/", en: "News", fa: "خبرها" },
  { href: "/market", en: "Asset timeline", fa: "نمودار دارایی‌ها" },
  { href: "/collection", en: "Collection", fa: "گردآوری", staff: true },
  { href: "/classification", en: "Classification", fa: "دسته‌بندی", staff: true },
  { href: "/evaluation", en: "Evaluation", fa: "ارزیابی", staff: true },
  { href: "/articles", en: "Articles", fa: "مقالات", staff: true },
  { href: "/review/swipe", en: "Quick review", fa: "بازبینی سریع", staff: true },
];

const AUTH_PATHS = ["/login", "/signup"];

export default function AppShell({ children, user = null, lang = "en" }) {
  const pathname = usePathname();
  const isAuth = AUTH_PATHS.some((path) => pathname.startsWith(path));
  // Reader routes follow the system light/dark theme; staff pages stay dark-only.
  const theme = pathname === "/" || pathname.startsWith("/events") ? "reader-theme" : "";

  if (isAuth) {
    return <div className="min-h-screen bg-paper">{children}</div>;
  }

  return (
    <div className={`${theme} min-h-screen bg-paper text-ink`}>
      <a
        href="#main"
        className="sr-only focus:not-sr-only focus:absolute focus:left-3 focus:top-3 focus:z-50 focus:rounded-md focus:bg-accent-strong focus:px-3 focus:py-2 focus:text-sm focus:font-medium focus:text-white"
      >
        {lang === "fa" ? "رفتن به محتوا" : "Skip to content"}
      </a>
      <header className="sticky top-0 z-20 border-b border-line bg-paper/90 backdrop-blur">
        <div className="mx-auto flex max-w-7xl flex-wrap items-center gap-3 px-3 py-3 sm:gap-6 sm:px-5">
          <Link href="/" className="shrink-0 text-sm font-bold tracking-tight text-ink">
            News<span className="text-accent">Intel</span>
          </Link>
          <nav aria-label={lang === "fa" ? "اصلی" : "Main"} className="order-3 flex min-w-0 basis-full flex-wrap gap-1 text-sm sm:order-none sm:basis-auto sm:flex-1">
            {NAV.filter((item) => !item.staff || user?.isStaff).map((item) => {
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
                  className={`rounded-md px-2 py-1 transition focus-visible:outline-2 focus-visible:outline-accent ${
                    active
                      ? "bg-card-2 text-ink"
                      : "text-muted hover:bg-card-2 hover:text-ink"
                  }`}
                >
                  {item[lang]}
                </Link>
              );
            })}
          </nav>
          <div className="ms-auto flex min-w-0 flex-wrap items-center justify-end gap-3 sm:flex-nowrap">
            <form action="/language" method="post">
              <input type="hidden" name="language" value={lang === "fa" ? "en" : "fa"} />
              <input type="hidden" name="next" value={pathname} />
              <button type="submit" className="rounded-md border border-line px-2 py-1 text-xs text-ink hover:bg-card-2">
                {lang === "fa" ? "English" : "فارسی"}
              </button>
            </form>
            {user ? (
              <span className="max-w-[12ch] truncate text-xs text-muted sm:max-w-none">
                {user.username}
              </span>
            ) : null}
            {user?.isStaff ? (
              <a
                href="/admin/"
                className="text-xs text-muted transition hover:text-ink"
              >
                {lang === "fa" ? "مدیریت" : "Admin"}
              </a>
            ) : null}
            {user ? <form action="/logout" method="post">
              <button
                type="submit"
                className="text-xs text-muted transition hover:text-ink"
              >
                {lang === "fa" ? "خروج" : "Sign out"}
              </button>
            </form> : <Link href="/login" className="text-xs text-muted hover:text-ink">{lang === "fa" ? "ورود" : "Sign in"}</Link>}
          </div>
        </div>
      </header>
      <main id="main" tabIndex={-1} className="mx-auto max-w-7xl px-3 py-6 sm:px-5 sm:py-8">
        {children}
      </main>
    </div>
  );
}
