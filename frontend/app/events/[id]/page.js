import Link from "next/link";
import { notFound } from "next/navigation";
import { ApiError, apiGet } from "@/lib/api";
import { tehranTime } from "@/lib/display";
import { language, label } from "@/lib/language";

export const dynamic = "force-dynamic";

export default async function EventDetail({ params }) {
  const { id } = await params;
  let event;
  try { event = await apiGet(`/api/public/events/${encodeURIComponent(id)}/`); }
  catch (error) { if (error instanceof ApiError && error.status === 404) notFound(); throw error; }
  const lang = await language();
  const tr = (en, fa) => label(lang, en, fa);
  return <article className="mx-auto max-w-3xl space-y-6">
    <Link href="/" className="text-sm text-emerald-400">{tr("← Back to news", "بازگشت به خبرها ←")}</Link>
    <header><p className="text-sm text-slate-400">{tehranTime(event.event_time)} · {event.status}</p>
      <h1 className="mt-2 text-3xl font-semibold leading-relaxed" dir="auto">{lang === "fa" ? event.title : (event.title_en || event.original_title)}</h1>
      {(lang === "fa" ? event.title_fa : event.title_en) ? <p className="mt-2 text-slate-400" dir="auto">{event.original_title}</p> : null}
    </header>
    {event.image_url ? <img src={event.image_url} alt="" className="max-h-96 w-full rounded-xl object-cover" /> : null}
    {(lang === "fa" ? event.brief_fa : event.brief_en) ? <section className="rounded-xl border border-slate-800 bg-slate-900 p-5 leading-8" dir={lang === "fa" ? "rtl" : "ltr"}>
      <h2 className="mb-2 font-semibold">{tr("Reported facts", "گزارش و شواهد")}</h2>
      <p>{lang === "fa" ? event.brief_fa : event.brief_en}</p>
    </section> : <p className="rounded-lg bg-amber-950/40 p-4 text-amber-200">{tr("Developing: assessment is pending.", "خبر در حال تکمیل است؛ ارزیابی هنوز آماده نیست.")}</p>}
    {(lang === "fa" ? event.channels_fa : event.channels_en) ? <section className="rounded-xl border border-slate-800 p-5" dir={lang === "fa" ? "rtl" : "ltr"}>
      <h2 className="mb-2 font-semibold">{tr("Possible channels", "مسیرهای احتمالی اثر")}</h2>
      <p className="text-sm leading-7 text-slate-300">{lang === "fa" ? event.channels_fa : event.channels_en}</p>
    </section> : null}
    {(lang === "fa" ? event.uncertainty_fa : event.uncertainty_en) ? <p className="text-sm text-amber-200" dir={lang === "fa" ? "rtl" : "ltr"}>
      {tr("Uncertainty: ", "عدم قطعیت: ")}{lang === "fa" ? event.uncertainty_fa : event.uncertainty_en}
    </p> : null}
    <p className="text-sm text-slate-400">{tr("Possible relevance is an assessment, not a forecast or proof of a price effect.", "اهمیت احتمالی یک ارزیابی است؛ پیش‌بینی یا اثبات اثر بر قیمت نیست.")}</p>
    <section><h2 className="mb-3 text-lg font-semibold">{tr("Sources and evidence", "منابع و شواهد")}</h2>
      <div className="grid gap-3">{event.sources.map((source) => <div key={source.url} className="rounded-lg border border-slate-800 p-4">
        <a href={source.url} target="_blank" rel="noopener noreferrer" className="font-medium text-emerald-300 hover:underline" dir="auto">{source.headline}</a>
        <p className="mt-1 text-xs text-slate-500">{source.original_outlet || source.name} · {tehranTime(source.published_at || source.first_seen_at)}</p>
        {source.lead ? <p className="mt-2 text-sm text-slate-300" dir="auto">{source.lead}</p> : null}
      </div>)}</div>
    </section>
    {event.history?.length ? <section>
      <h2 className="mb-3 text-lg font-semibold">{tr("Corrections and removals", "اصلاح‌ها و حذف‌ها")}</h2>
      <ul className="space-y-2 text-sm text-slate-400">{event.history.map((change, index) =>
        <li key={`${change.observed_at}-${index}`} className="rounded-lg border border-slate-800 p-3">
          {change.source} · {tehranTime(change.observed_at)} · {change.previous_status}
          <span className="block" dir="auto">{change.previous_headline}</span>
        </li>)}</ul>
    </section> : null}
  </article>;
}
