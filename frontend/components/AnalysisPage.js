import Link from "next/link";
import ArticleCard from "@/components/ArticleCard";
import { apiGet } from "@/lib/api";
import { number, tehranTime } from "@/lib/display";
import { language, label } from "@/lib/language";
import { Card, CircuitBanner, Metric, SectionTitle } from "@/components/primitives";
import { staffDenied } from "@/components/StaffGate";

export default async function AnalysisPage({ stage }) {
  const denied = await staffDenied();
  if (denied) return denied;
  const classified = stage === "classification";
  const [summary, articles, lang] = await Promise.all([
    apiGet(`/api/analysis-summary/?stage=${stage}`),
    apiGet(`/api/articles/?limit=8&${classified ? "classified" : "evaluated"}=true&order=stored&include_duplicates=true`),
    language(),
  ]);
  const tr = (en, fa) => label(lang, en, fa);
  const title = classified ? tr("Classification", "دسته‌بندی") : tr("Evaluation", "ارزیابی");
  const resultFilter = classified ? "classified" : "evaluated";
  const eventTotal = summary.events_24h.reduce((sum, event) => sum + event.count, 0);

  return <div className="space-y-8">
    <div>
      <p className="text-xs uppercase tracking-[0.16em] text-emerald-400">{tr("Analysis pipeline", "فرآیند تحلیل")}</p>
      <h1 className="mt-2 text-2xl font-semibold sm:text-3xl">{title}</h1>
      <p className="mt-2 text-sm text-slate-400">
        {tr("Coverage counts articles with a stored result, including older results; it is not the processing queue.", "پوشش، مقالات دارای نتیجه ذخیره‌شده را می‌شمارد، از جمله نتایج قدیمی؛ این عدد صف پردازش نیست.")}
      </p>
    </div>
    <CircuitBanner circuit={summary.circuit} />
    <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
      <Metric label={tr("Articles with result", "مقالات دارای نتیجه")} value={number(summary.completed)} />
      <Metric label={tr("Without result", "بدون نتیجه")} value={number(summary.without_result)} />
      <Metric label={tr("Total stored", "کل ذخیره‌شده")} value={number(summary.total)} />
      <Metric label={tr("Events in 24h", "رویدادهای ۲۴ ساعت")} value={number(eventTotal)} />
    </div>
    <Card className="p-4 text-sm">
      <p>{tr("Last result", "آخرین نتیجه")}: <strong>{tehranTime(summary.last_result_at)}</strong></p>
      <p className="mt-2 text-xs text-slate-500">{tr("Event outcomes in the past 24 hours", "نتیجه رویدادها در ۲۴ ساعت گذشته")}: {summary.events_24h.length ? summary.events_24h.map((event) => `${event.status}: ${number(event.count)}`).join(" · ") : tr("No recorded events", "رویدادی ثبت نشده")}</p>
    </Card>
    {classified && <section>
      <SectionTitle>{tr("Latest category per article", "آخرین دسته هر مقاله")}</SectionTitle>
      <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">{summary.categories.map((row) =>
        <Metric key={row.category} label={row.category} value={number(row.count)} />
      )}</div>
    </section>}
    <section>
      <div className="mb-3 flex flex-wrap items-center justify-between gap-3">
        <SectionTitle>{tr("Recently stored articles with a result", "مقالات تازه ذخیره‌شده دارای نتیجه")}</SectionTitle>
        <div className="flex gap-3 text-sm">
          <Link href={`/articles?${resultFilter}=true&order=stored&include_duplicates=true`} className="text-emerald-300 hover:underline">{tr("View results", "دیدن نتایج")}</Link>
          <Link href={`/articles?${resultFilter}=false&order=stored&include_duplicates=true`} className="text-amber-300 hover:underline">{tr("View without result", "دیدن بدون نتیجه")}</Link>
        </div>
      </div>
      {articles.results.length ? <div className="grid gap-3">{articles.results.map((article) =>
        <ArticleCard key={article.id} article={article} />
      )}</div> : <Card className="p-6 text-sm text-slate-400">{tr("No articles have a result yet.", "هنوز مقاله‌ای نتیجه ندارد.")}</Card>}
    </section>
  </div>;
}
