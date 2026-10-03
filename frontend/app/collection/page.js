import Link from "next/link";
import { apiGet } from "@/lib/api";
import { number, tehranTime } from "@/lib/display";
import { language, label } from "@/lib/language";
import { Card, Metric, SectionTitle, TableScroll } from "@/components/primitives";
import { staffDenied } from "@/components/StaffGate";

export const metadata = { title: "Collection · News Intelligence" };
export const dynamic = "force-dynamic";

function stateTone(state) {
  if (state === "healthy" || state === "success") return "text-emerald-300";
  if (state === "disabled") return "text-slate-500";
  return "text-amber-300";
}

export default async function CollectionPage({ searchParams }) {
  const denied = await staffDenied();
  if (denied) return denied;
  const params = (await searchParams) || {};
  const days = [1, 7, 14, 30].includes(Number(params.days)) ? Number(params.days) : 14;
  const [data, lang] = await Promise.all([apiGet(`/api/collection/?days=${days}`), language()]);
  const tr = (en, fa) => label(lang, en, fa);
  const attempts = data.attempt_totals;
  const sources = data.sources;

  return <div className="space-y-8">
    <div>
      <p className="text-xs uppercase tracking-[0.16em] text-emerald-400">{tr("Collection monitor", "پایش گردآوری")}</p>
      <h1 className="mt-2 text-2xl font-semibold sm:text-3xl">{tr("News collection", "گردآوری خبر")}</h1>
      <p className="mt-2 text-sm text-slate-400">
        {tr("Newly stored articles by Tehran calendar day and source.", "مقالات تازه ذخیره‌شده بر اساس روز تقویمی تهران و منبع.")}
        {" "}{tr("Updated", "به‌روزرسانی")}: {tehranTime(data.as_of)}
      </p>
    </div>
    <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
      <Metric label={tr("New today", "جدید امروز")} value={number(data.today)} />
      <Metric label={tr(`New in ${days} days`, `جدید در ${days} روز`)} value={number(data.new)} />
      <Metric label={tr("Repeat sightings", "مشاهده‌های تکراری")} value={number(attempts.repeated ?? 0)}
        hint={data.tracking_started_at ? tr("Since attempt tracking began", "از آغاز ثبت تلاش‌ها") : tr("Tracking starts after this update", "ثبت تلاش‌ها پس از این به‌روزرسانی آغاز می‌شود")} />
      <Metric label={tr("Failed article ingests", "خطای ذخیره مقاله")} value={number(attempts.failed ?? 0)} />
    </div>

    <section>
      <div className="mb-3 flex flex-wrap items-center justify-between gap-3">
        <SectionTitle>{tr("Daily collection", "گردآوری روزانه")}</SectionTitle>
        <div className="flex gap-2 text-sm">{[1, 7, 14, 30].map((window) =>
          <Link key={window} href={`/collection?days=${window}`} aria-current={days === window ? "page" : undefined}
            className={`rounded-md px-2 py-1 ${days === window ? "bg-emerald-900 text-emerald-200" : "text-slate-400 hover:bg-slate-800"}`}>
            {window}{tr("d", " روز")}
          </Link>
        )}</div>
      </div>
      <Card className="p-3 sm:p-5"><TableScroll><table className="w-full min-w-[580px] text-sm">
        <thead><tr className="border-b border-slate-800 text-slate-400">
          <th scope="col" className="p-2 text-start">{tr("Day (Tehran)", "روز (تهران)")}</th>
          {sources.map((source) => <th scope="col" key={source.name} className="p-2 text-end">{source.display_name}</th>)}
          <th scope="col" className="p-2 text-end">{tr("Total", "مجموع")}</th>
        </tr></thead>
        <tbody>{[...data.daily].reverse().map((row) => <tr key={row.day} className="border-b border-slate-800/60 last:border-0">
          <th scope="row" className="p-2 text-start font-medium tabular">{row.day}</th>
          {sources.map((source) => <td key={source.name} className="p-2 text-end tabular">
            <Link className="text-emerald-300 hover:underline" href={`/articles?stored_day=${row.day}&source=${encodeURIComponent(source.name)}&order=stored&include_duplicates=true`}>
              {number(row.sources[source.name] || 0)}
            </Link>
          </td>)}
          <td className="p-2 text-end font-semibold tabular">{number(row.new)}</td>
        </tr>)}</tbody>
      </table></TableScroll></Card>
    </section>

    <section>
      <SectionTitle>{tr("Sources", "منابع")}</SectionTitle>
      <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-3">{sources.map((source) => <Card key={source.name} className="p-4">
        <div className="flex items-start justify-between gap-3">
          <h3 className="font-medium">{source.display_name}</h3>
          <span className={`text-xs font-medium ${stateTone(source.state)}`}>{source.state}</span>
        </div>
        <p className="mt-3 text-sm text-slate-400">{tr("New today", "جدید امروز")}: <strong className="text-slate-100">{number(source.today)}</strong></p>
        <p className="mt-1 text-xs text-slate-500">{tr("Last new article", "آخرین مقاله جدید")}: {tehranTime(source.last_new_at)}</p>
        <p className="mt-1 text-xs text-slate-500">{tr("Last attempt", "آخرین تلاش")}: {source.latest_attempt ? `${source.latest_attempt.status} · ${tehranTime(source.latest_attempt.started_at)}` : tr("Not yet tracked", "هنوز ثبت نشده")}</p>
      </Card>)}</div>
    </section>

    <section>
      <SectionTitle>{tr("Collection quality", "کیفیت گردآوری")}</SectionTitle>
      <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
        <Metric label={tr("Duplicates", "تکراری‌ها")} value={number(data.quality.duplicates)} />
        <Metric label={tr("Feed or listing only", "فقط خوراک یا فهرست")} value={number(data.quality.feed_only)} />
        <Metric label={tr("Empty bodies", "متن خالی")} value={number(data.quality.empty_body)} />
        <Metric label={tr("Quality flagged", "دارای هشدار کیفیت")} value={number(data.quality.quality_flagged)} />
      </div>
      <p className="mt-2 text-xs text-slate-500">{tr("Quality counts use newly stored articles in the selected window; categories may overlap.", "شمارش کیفیت بر اساس مقالات تازه در بازه انتخابی است؛ دسته‌ها ممکن است هم‌پوشانی داشته باشند.")}</p>
    </section>

    <section>
      <SectionTitle>{tr("Recent crawl attempts", "تلاش‌های اخیر گردآوری")}</SectionTitle>
      {data.recent_attempts.length ? <div className="grid gap-2">{data.recent_attempts.map((attempt) =>
        <Card key={attempt.id} className="flex flex-wrap items-center justify-between gap-3 p-3 text-sm">
          <div><strong>{attempt.source}</strong><span className="ms-3 text-slate-500">{tehranTime(attempt.started_at)}</span></div>
          <div className="flex flex-wrap gap-3 text-xs tabular">
            <span className={stateTone(attempt.status)}>{attempt.status}</span>
            <span>{tr("new", "جدید")}: {number(attempt.new)}</span>
            <span>{tr("repeat", "تکراری")}: {number(attempt.repeated)}</span>
            <span>{tr("failed", "خطا")}: {number(attempt.failed)}</span>
          </div>
        </Card>
      )}</div> : <Card className="p-6 text-sm text-slate-400">{tr("Crawl attempt history begins after this update.", "تاریخچه تلاش‌های گردآوری پس از این به‌روزرسانی آغاز می‌شود.")}</Card>}
    </section>
  </div>;
}
