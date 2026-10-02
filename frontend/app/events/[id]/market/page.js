import Link from "next/link";
import PriceChart from "@/components/PriceChart";
import { Icon, TierBadge } from "@/components/reader";
import { apiGet } from "@/lib/api";
import { language, label } from "@/lib/language";
import { RANGE_DAYS, digits, headline, linkedAssets, rangeFor } from "@/lib/reader";
import { loadEvent } from "../load";

export const metadata = { title: "Market impact · News Intelligence" };
export const dynamic = "force-dynamic";

const CAVEATS = {
  stale_or_closed_market: ["No recent prices: the market may be closed or the feed stale.", "قیمت تازه‌ای نیست؛ بازار ممکن است تعطیل یا داده قدیمی باشد."],
  no_price_observations: ["No price observations in this window.", "در این بازه قیمتی ثبت نشده است."],
  portfolio_feed_unavailable: ["The price feed for this asset is unavailable right now.", "دادهٔ قیمت این دارایی فعلاً در دسترس نیست."],
};
const WINDOWS = { "1d": ["1 day later", "یک روز بعد"], "1w": ["1 week later", "یک هفته بعد"] };

function Change({ result, lang, name }) {
  const up = result.percent > 0;
  const flat = result.percent === 0;
  return <div className="rounded-xl border border-line bg-card-2 p-3">
    <p className="text-xs text-muted">{name}</p>
    <p className="mt-1 flex items-center gap-1 text-lg font-bold tabular">
      <span aria-hidden="true">{flat ? "→" : up ? "▲" : "▼"}</span>
      <span dir="ltr">{digits(Math.abs(result.percent), lang)}{lang === "fa" ? "٪" : "%"}</span>
      <span className="sr-only">{flat ? "" : up ? (lang === "fa" ? "افزایش" : "up") : (lang === "fa" ? "کاهش" : "down")}</span>
    </p>
  </div>;
}

export default async function MarketImpact({ params, searchParams }) {
  const [{ id }, query] = await Promise.all([params, searchParams]);
  const event = await loadEvent(id);
  const lang = await language();
  const tr = (en, fa) => label(lang, en, fa);
  const catalog = await apiGet("/api/public/assets/");
  const assets = linkedAssets(event.asset_scores, catalog.results);
  const asset = assets.find((row) => row.key === query?.asset) || assets[0];
  const range = rangeFor(event.event_time);
  let timeline = null;
  try {
    timeline = asset ? await apiGet(`/api/public/assets/${asset.key}/timeline/?range=${range}&events=all`) : null;
  } catch {
    timeline = null;
  }
  const end = timeline ? new Date(timeline.as_of).getTime() : Date.now();
  const start = end - RANGE_DAYS[range] * 86400000;
  const changes = timeline?.events.find((row) => row.event.id === event.id)?.observed_changes || {};
  const name = (row) => (lang === "fa" ? row.name_fa : row.name);

  return <div className="mx-auto max-w-3xl space-y-6">
    <nav className="text-sm">
      <Link href={`/events/${event.id}`} className="inline-flex items-center gap-1 text-accent hover:underline">
        <Icon name="arrow" className="h-4 w-4 rotate-180 rtl:rotate-0" />{tr("Back to the report", "بازگشت به خبر")}
      </Link>
    </nav>
    <header className="space-y-2">
      <h1 className="text-3xl font-extrabold">{tr("Market impact", "اثر بر بازار")}</h1>
      <p className="leading-7 text-muted" dir="auto">{headline(event, lang)}</p>
    </header>

    {assets.length ? <nav aria-label={tr("Assets", "دارایی‌ها")} className="-mx-3 flex gap-2 overflow-x-auto px-3 pb-1 sm:mx-0 sm:flex-wrap sm:px-0">
      {assets.map((row) => <Link key={row.key} href={`/events/${event.id}/market?asset=${row.key}`}
        aria-current={row.key === asset.key ? "page" : undefined}
        className={`shrink-0 rounded-full border px-4 py-2 text-sm transition focus-visible:outline-2 focus-visible:outline-accent ${row.key === asset.key ? "border-accent-strong bg-accent-strong font-semibold text-white" : "border-line bg-card text-muted hover:text-ink"}`}>
        {name(row)}
      </Link>)}
    </nav> : null}

    <section className="space-y-4 rounded-2xl border border-line bg-card p-4 sm:p-6">
      {asset ? <div className="flex flex-wrap items-center justify-between gap-2">
        <h2 className="text-lg font-bold">{name(asset)} <span className="text-sm font-normal text-muted">({timeline?.asset.unit || asset.unit})</span></h2>
        {event.asset_scores?.[asset.class] != null ? <span className="flex items-center gap-2 text-xs text-muted">
          {tr("Assessed relevance", "ارتباط ارزیابی‌شده")} <TierBadge tier={event.asset_tiers?.[asset.class]} lang={lang} prefix={false} />
        </span> : null}
      </div> : null}
      {timeline?.points.length
        ? <PriceChart points={timeline.points} start={start} end={end} eventTime={event.event_time} lang={lang} assetName={name(asset)} />
        : <p className="py-16 text-center text-muted">{tr("No price data to chart for this asset yet.", "هنوز دادهٔ قیمتی برای نمایش این دارایی وجود ندارد.")}</p>}
      {new Date(event.event_time).getTime() < start ? <p className="text-sm text-muted">{tr("This event is older than the chart window.", "این رویداد قدیمی‌تر از بازهٔ نمودار است.")}</p> : null}
      {(timeline?.caveats || []).filter((code) => CAVEATS[code]).map((code) => <p key={code} className="flex items-center gap-2 text-sm text-muted">
        <Icon name="info" className="h-4 w-4 shrink-0" />{label(lang, ...CAVEATS[code])}
      </p>)}
      {Object.keys(changes).length ? <div className="grid grid-cols-2 gap-3">
        {Object.entries(changes).map(([window, result]) => <Change key={window} result={result} lang={lang} name={label(lang, ...WINDOWS[window])} />)}
      </div> : null}
      <p className="text-xs leading-6 text-muted">{tr(
        "Price moves after an event are observed associations, not proof that the event caused them. Source: " + (timeline?.asset.provider || asset?.provider || "—") + ".",
        "تغییر قیمت پس از رویداد یک هم‌زمانی مشاهده‌شده است، نه اثبات اینکه رویداد علت آن بوده است. منبع قیمت: " + (timeline?.asset.provider || asset?.provider || "—") + ".")}</p>
    </section>
  </div>;
}
