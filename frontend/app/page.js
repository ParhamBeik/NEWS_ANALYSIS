import Link from "next/link";
import EventCard from "@/components/EventCard";
import AlertOptIn from "@/components/AlertOptIn";
import { apiGet, currentUser } from "@/lib/api";
import { language, label } from "@/lib/language";

export const metadata = { title: "News · News Intelligence" };
export const dynamic = "force-dynamic";

const PERIODS = [
  ["now", "Now", "اکنون"], ["today", "Today", "امروز"],
  ["week", "Week", "هفته"], ["latest", "Latest", "تازه‌ترین"],
];

export default async function NewsHome({ searchParams }) {
  const params = await searchParams;
  const period = PERIODS.some(([key]) => key === params?.period) ? params.period : "now";
  const lang = await language();
  const [data, alertConfig, user] = await Promise.all([
    apiGet(`/api/public/events/?period=${period}`),
    apiGet("/api/public/alert-config/"), currentUser(),
  ]);
  const tr = (en, fa) => label(lang, en, fa);
  return <div className="space-y-6">
    <header className="flex flex-wrap items-end justify-between gap-3">
      <div><p className="text-xs uppercase tracking-widest text-emerald-400">News Intelligence</p>
        <h1 className="mt-2 text-3xl font-semibold">{tr("Important news", "خبرهای مهم")}</h1>
        <p className="mt-2 text-sm text-slate-400">{tr("Iran-relevant economic and geopolitical events, with their sources.", "رویدادهای مهم اقتصادی و ژئوپلیتیک برای ایران، همراه با منابع.")}</p>
      </div>
      <Link href="/market" className="rounded-lg bg-emerald-700 px-4 py-2 text-sm font-medium text-white hover:bg-emerald-600">{tr("Explore asset charts", "مشاهده نمودار دارایی‌ها")}</Link>
    </header>
    <AlertOptIn publicKey={alertConfig.public_key} signedIn={Boolean(user)} lang={lang} />
    <nav aria-label={tr("News period", "بازهٔ خبرها")} className="flex flex-wrap gap-2">
      {PERIODS.map(([key, en, fa]) => <Link key={key} href={key === "now" ? "/" : `/?period=${key}`}
        aria-current={period === key ? "page" : undefined}
        className={`rounded-full px-4 py-2 text-sm ${period === key ? "bg-emerald-800 text-white" : "bg-slate-900 text-slate-400 hover:text-white"}`}>
        {label(lang, en, fa)}
      </Link>)}
    </nav>
    {data.results.length ? <div className="grid gap-3">{data.results.map((event) => <EventCard key={event.id} event={event} lang={lang} />)}</div>
      : <div className="rounded-xl border border-slate-800 p-10 text-center text-slate-400">{tr("No events in this period yet.", "هنوز رویدادی در این بازه ثبت نشده است.")}</div>}
  </div>;
}
