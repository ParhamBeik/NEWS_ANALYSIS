import Link from "next/link";
import { EVENT_CATEGORY as CATEGORY, tehranTime } from "@/lib/display";

export default function EventCard({ event, lang = "fa" }) {
  const persian = lang === "fa";
  const title = persian ? (event.title_fa || event.original_title) : (event.title_en || event.original_title);
  const brief = persian ? event.brief_fa : event.brief_en;
  const category = CATEGORY[event.category];
  return <article className="overflow-hidden rounded-xl border border-slate-800 bg-slate-900/60">
    <div className="flex flex-col sm:flex-row">
      {event.image_url ? <img src={event.image_url} alt="" className="aspect-video w-full object-cover sm:w-48" /> : null}
      <div className="min-w-0 flex-1 p-4">
        <div className="flex flex-wrap items-center gap-2 text-xs text-slate-400">
          <span>{category ? category[persian ? 1 : 0] : (persian ? "در حال بررسی" : "Assessing")}</span>
          <span aria-hidden="true">·</span>
          <time dateTime={event.event_time}>{tehranTime(event.event_time)}</time>
          {event.status === "developing" ? <span className="rounded bg-amber-950 px-2 py-0.5 text-amber-300">{persian ? "در حال تکمیل" : "Developing"}</span> : null}
        </div>
        <h2 className="mt-2 text-lg font-semibold leading-relaxed" dir="auto">
          <Link href={`/events/${event.id}`} className="hover:text-emerald-300">{title}</Link>
        </h2>
        {(persian ? event.title_fa : event.title_en) && event.original_title !== title ?
          <p className="mt-1 text-sm text-slate-500" dir="auto">{event.original_title}</p> : null}
        {brief ? <p className="mt-2 text-sm leading-7 text-slate-300" dir="auto">{brief}</p> : null}
        <div className="mt-3 flex flex-wrap gap-x-4 gap-y-1 text-xs text-slate-400">
          <span>{event.sources.map((source) => source.name).join(" · ")}</span>
          {event.iran_score != null ? <span>{persian ? "اهمیت برای ایران" : "Iran relevance"}: {event.iran_score}/100</span> : null}
          {event.global_score != null ? <span>{persian ? "اهمیت جهانی" : "Global significance"}: {event.global_score}/100</span> : null}
        </div>
      </div>
    </div>
  </article>;
}
