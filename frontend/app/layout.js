import Link from "next/link";
import "./globals.css";

export const metadata = {
  title: "News Intelligence",
  description: "Persian security and macroeconomic news analysis",
};

/**
 * `lang="en" dir="ltr"` on the document, with Persian content marked RTL where it appears.
 *
 * The chrome is English and the content is Persian, so a document-level RTL would mirror
 * every dashboard, table and chart to fix the direction of the headlines. Setting
 * direction at the content boundary is the smaller, correct change.
 */

const NAV = [
  { href: "/", label: "Feed" },
  { href: "/ab", label: "A/B lab" },
  { href: "/review", label: "Review" },
  { href: "/kpi", label: "Quality" },
  { href: "/market", label: "Market" },
  { href: "/ops", label: "Ops" },
  { href: "/exports", label: "Exports" },
];

export default function RootLayout({ children }) {
  return (
    <html lang="en" dir="ltr">
      <body className="min-h-screen bg-slate-950">
        <header className="sticky top-0 z-20 border-b border-slate-800 bg-slate-950/85 backdrop-blur">
          <div className="mx-auto flex max-w-7xl items-center gap-6 px-5 py-3">
            <Link href="/" className="text-sm font-semibold tracking-tight text-slate-100">
              News<span className="text-emerald-400">Intel</span>
            </Link>
            <nav className="flex flex-wrap gap-1 text-sm">
              {NAV.map((item) => (
                <Link
                  key={item.href}
                  href={item.href}
                  className="rounded-md px-2.5 py-1 text-slate-400 transition hover:bg-slate-900 hover:text-slate-100"
                >
                  {item.label}
                </Link>
              ))}
            </nav>
            {/* Not under /api: that prefix belongs to Django, and a Next route squatting
                on it would shadow a real endpoint the day one is added there. */}
            <form action="/logout" method="post" className="ml-auto">
              <button className="text-xs text-slate-500 transition hover:text-slate-300">
                Sign out
              </button>
            </form>
          </div>
        </header>
        <main className="mx-auto max-w-7xl px-5 py-8">{children}</main>
      </body>
    </html>
  );
}
