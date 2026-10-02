import Link from "next/link";
import PriceChart from "@/components/PriceChart";
import { Icon } from "@/components/reader";
import { apiGet } from "@/lib/api";
import { language, label } from "@/lib/language";
import { POLICY_CALENDAR, direction, displayPrice, nextMeeting, sparkPath } from "@/lib/macro";
import { digits, jalali } from "@/lib/reader";

export const metadata = { title: "Macro dashboard · News Intelligence" };
export const dynamic = "force-dynamic";

const CAVEATS = {
  market_closed: ["Market closed", "بازار بسته است"],
  stale_quote: ["Stale quote", "قیمت قدیمی"],
  stale_series: ["No recent prices", "قیمت تازه‌ای نیست"],
  source_unavailable: ["Source unavailable", "منبع در دسترس نیست"],
  portfolio_feed_unavailable: ["Price feed unavailable", "دادهٔ قیمت در دسترس نیست"],
  no_quote: ["No quote", "بدون قیمت"],
  no_points: ["No prices in this window", "در این بازه قیمتی نیست"],
};

function NotConnected({ tr }) {
  return <section className="rounded-2xl border border-dashed border-line bg-card p-8 text-center">
    <Icon name="info" className="mx-auto h-6 w-6 text-muted" />
    <h2 className="mt-3 text-lg font-bold">{tr("Price service not connected yet", "سرویس قیمت هنوز متصل نشده است")}</h2>
    <p className="mt-2 text-sm leading-7 text-muted">{tr(
      "Macro prices come from the Portfolio app. They will appear here once it is connected.",
      "قیمت‌های کلان از برنامهٔ پورتفولیو خوانده می‌شوند و پس از اتصال در این صفحه نمایش داده می‌شوند.")}</p>
  </section>;
}

function Calendar({ lang, tr, yieldTile }) {
  const two = yieldTile ? displayPrice(yieldTile.price, "", lang) : null;
  return <section aria-labelledby="calendar" className="rounded-2xl border border-line bg-card p-4 sm:p-6">
    <h2 id="calendar" className="text-lg font-bold">{tr("Policy rates and meetings", "نرخ بهره و جلسات بانک‌های مرکزی")}</h2>
    <div className="mt-4 grid gap-3 sm:grid-cols-3">
      {POLICY_CALENDAR.map((bank) => {
        const next = nextMeeting(bank);
        return <div key={bank.key} className="rounded-xl border border-line bg-card-2 p-3">
          <p className="text-sm font-semibold">{lang === "fa" ? bank.name_fa : bank.name_en}</p>
          <p className="mt-1 text-xs text-muted">{tr("Policy rate", "نرخ سیاستی")}: <span className="tabular">{bank.rate ?? "—"}</span></p>
          <p className="mt-2 text-sm">{next
            ? <>{tr("Next decision", "تصمیم بعدی")}: <span className="font-semibold">{jalali(`${next.date}T12:00:00Z`, lang, { time: false })}</span>
              <span className="text-muted"> ({digits(next.days, lang)} {tr("days", "روز")})</span></>
            : <span className="text-muted">{tr("No published meeting schedule", "برنامهٔ جلسات منتشر نشده است")}</span>}</p>
          <a href={bank.source} className="mt-2 inline-block text-xs text-accent hover:underline" rel="noreferrer" target="_blank">{tr("Source", "منبع")}</a>
        </div>;
      })}
    </div>
    {two && yieldTile.price ? <p className="mt-3 text-sm text-muted">
      {tr("Market-implied path: US 2Y Treasury yield", "انتظار بازار از نرخ بهره: بازده اوراق ۲ سالهٔ آمریکا")}{" "}
      <span className="font-semibold text-ink tabular" dir="ltr">{two.text}%</span>
    </p> : null}
  </section>;
}

function Tile({ tile, lang, selected }) {
  const price = displayPrice(tile.price, tile.unit, lang);
  const path = sparkPath(tile.spark);
  const change = Number(tile.change_pct);
  const caveats = (tile.caveats || []).filter((code) => CAVEATS[code]);
  return <Link href={`/macro?key=${tile.key}`} scroll={false} aria-current={selected ? "true" : undefined}
    className={`block rounded-xl border p-3 transition focus-visible:outline-2 focus-visible:outline-accent ${selected ? "border-accent bg-card-2" : "border-line bg-card hover:bg-card-2"}`}>
    <p className="truncate text-sm text-muted">{lang === "fa" ? tile.name_fa : tile.name_en}</p>
    <p className="mt-1 flex items-baseline gap-1">
      <span className="text-lg font-bold tabular" dir="ltr">{price.text}</span>
      <span className="text-xs text-muted">{price.unit}</span>
    </p>
    <p className="flex items-center gap-1 text-xs text-muted tabular">
      <span aria-hidden="true">{direction(tile.change_pct)}</span>
      <span dir="ltr">{Number.isFinite(change) && tile.change_pct !== null ? `${digits(Math.abs(change), lang)}${lang === "fa" ? "٪" : "%"}` : "—"}</span>
    </p>
    {path ? <svg viewBox="0 0 100 28" preserveAspectRatio="none" className="mt-2 h-7 w-full" aria-hidden="true">
      <path d={path} fill="none" stroke="var(--price-line)" strokeWidth="1.6" vectorEffect="non-scaling-stroke" />
    </svg> : <div className="mt-2 h-7" />}
    {caveats.length ? <p className="mt-1 truncate text-[11px] text-muted">{caveats.map((code) => label(lang, ...CAVEATS[code])).join(" · ")}</p> : null}
  </Link>;
}

export default async function MacroPage({ searchParams }) {
  const query = await searchParams;
  const lang = await language();
  const tr = (en, fa) => label(lang, en, fa);
  let data = null;
  try {
    data = await apiGet(`/api/public/macro/${query?.key ? `?key=${encodeURIComponent(query.key)}` : ""}`);
  } catch {
    data = null;
  }
  const connected = Boolean(data?.available);
  const tiles = connected ? data.groups.flatMap((group) => group.tiles) : [];
  const selected = data?.selected;
  const end = data?.as_of ? new Date(data.as_of).getTime() : Date.now();
  const start = end - 30 * 86400000;
  const name = (row) => (lang === "fa" ? row.name_fa : row.name_en);

  return <div className="mx-auto max-w-5xl space-y-6">
    <header className="space-y-2">
      <h1 className="text-3xl font-extrabold">{tr("Macro dashboard", "داشبورد کلان")}</h1>
      <p className="text-sm leading-7 text-muted">{tr(
        "Rates, currencies, commodities and markets that move Iran's economy, with the latest observed prices.",
        "نرخ بهره، ارز، کالا و بازارهایی که بر اقتصاد ایران اثر می‌گذارند، با آخرین قیمت‌های مشاهده‌شده.")}</p>
    </header>

    <Calendar lang={lang} tr={tr} yieldTile={tiles.find((tile) => tile.key === "us_treasury_2y")} />

    {!connected ? <NotConnected tr={tr} /> : <>
      {data.groups.map((group) => <section key={group.key} aria-labelledby={`group-${group.key}`} className="space-y-3">
        <h2 id={`group-${group.key}`} className="text-lg font-bold">{name(group)}</h2>
        <div className="grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-4">
          {group.tiles.map((tile) => <Tile key={tile.key} tile={tile} lang={lang} selected={tile.key === selected?.key} />)}
        </div>
      </section>)}

      {selected ? <section aria-labelledby="chart" className="space-y-3 rounded-2xl border border-line bg-card p-4 sm:p-6">
        <h2 id="chart" className="text-lg font-bold">{name(selected)} <span className="text-sm font-normal text-muted">
          ({tr("30 days", "۳۰ روز")} · {displayPrice(1, selected.unit, lang).unit})</span></h2>
        {selected.points.length
          ? <PriceChart points={selected.unit === "IRR" ? selected.points.map((p) => ({ ...p, price: Number(p.price) / 10 })) : selected.points}
            start={start} end={end} eventTime={null} lang={lang} assetName={name(selected)} />
          : <p className="py-16 text-center text-muted">{tr("No price data to chart for this series yet.", "هنوز دادهٔ قیمتی برای این سری وجود ندارد.")}</p>}
        {(selected.caveats || []).filter((code) => CAVEATS[code]).map((code) => <p key={code} className="flex items-center gap-2 text-sm text-muted">
          <Icon name="info" className="h-4 w-4 shrink-0" />{label(lang, ...CAVEATS[code])}
        </p>)}
        <p className="text-xs leading-6 text-muted">{tr("Daily closes. Source", "قیمت پایانی روزانه. منبع")}: {selected.provider || "—"}</p>
      </section> : null}
    </>}
  </div>;
}
