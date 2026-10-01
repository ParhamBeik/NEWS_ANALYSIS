import Link from "next/link";
import AssetTimeline from "@/components/AssetTimeline";
import { apiGet } from "@/lib/api";
import { language, label } from "@/lib/language";

export const metadata = { title: "Asset timeline · News Intelligence" };
export const dynamic = "force-dynamic";

const RANGES = ["1W", "1M", "3M", "1Y"];

export default async function MarketPage({ searchParams }) {
  const params = await searchParams;
  const lang = await language();
  const tr = (en, fa) => label(lang, en, fa);
  const catalog = await apiGet("/api/public/assets/");
  const symbol = catalog.results.some((asset) => asset.key === params?.symbol) ? params.symbol : "gold_18k";
  const range = RANGES.includes(params?.range) ? params.range : "1M";
  const showAll = params?.events === "all";
  const data = await apiGet(`/api/public/assets/${symbol}/timeline/?range=${range}&events=${showAll ? "all" : "relevant"}`);
  const link = (nextSymbol, nextRange, all = showAll) => `/market?symbol=${nextSymbol}&range=${nextRange}&events=${all ? "all" : "relevant"}`;
  return <div className="space-y-5">
    <header><h1 className="text-3xl font-semibold">{tr("Asset timeline", "نمودار دارایی‌ها")}</h1>
      <p className="mt-2 text-sm text-slate-400">{tr("Explore price observations beside potentially relevant news.", "قیمت‌های مشاهده‌شده را در کنار خبرهای مرتبط ببینید.")}</p>
    </header>
    <nav aria-label={tr("Assets", "دارایی‌ها")} className="flex flex-wrap gap-2">{catalog.results.map((asset) => <Link key={asset.key}
      href={link(asset.key, range)} aria-current={asset.key === symbol ? "page" : undefined}
      className={`rounded-lg px-3 py-2 text-sm ${asset.key === symbol ? "bg-emerald-800" : "bg-slate-900 text-slate-400"}`}>
      {lang === "fa" ? asset.name_fa : asset.name}</Link>)}</nav>
    <div className="flex flex-wrap items-center justify-between gap-3">
      <div className="flex gap-2">{RANGES.map((choice) => <Link key={choice} href={link(symbol, choice)}
        aria-current={choice === range ? "page" : undefined}
        className={`rounded px-3 py-1 text-sm ${choice === range ? "bg-slate-700" : "text-slate-400"}`}>{choice}</Link>)}</div>
      <Link href={link(symbol, range, !showAll)} className="rounded border border-slate-700 px-3 py-1 text-sm">
        {showAll ? tr("Relevant events", "فقط خبرهای مرتبط") : tr("All important events", "همهٔ خبرهای مهم")}</Link>
    </div>
    <div className="rounded-xl border border-slate-800 bg-slate-900/50 p-3 sm:p-5">
      <p className="mb-3 text-sm text-slate-400">{data.asset.provider} · {data.asset.unit} · {data.resolution} · {data.points.length} {tr("observations", "مشاهده")}</p>
      <p className="mb-3 text-xs text-slate-500">{tr("Last observation", "آخرین مشاهده")}: {data.last_observation_at ? new Date(data.last_observation_at).toLocaleString(lang === "fa" ? "fa-IR" : "en-US") : "—"}
        {data.gaps?.length ? ` · ${data.gaps.length} ${tr("gaps over 3 days", "فاصلهٔ بیش از سه روز")}` : ""}</p>
      {data.caveats?.length ? <p className="mb-3 text-xs text-amber-300">{data.caveats.join(" · ")}</p> : null}
      {data.points.length ? <AssetTimeline data={data} lang={lang} /> : <p className="py-20 text-center text-slate-400">{tr("No verified prices in this range.", "در این بازه قیمت تأییدشده‌ای موجود نیست.")}</p>}
    </div>
  </div>;
}
