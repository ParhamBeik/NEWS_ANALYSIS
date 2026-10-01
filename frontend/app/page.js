import Link from "next/link";
import AlertOptIn from "@/components/AlertOptIn";
import EventTile from "@/components/EventTile";
import { Icon } from "@/components/reader";
import { apiGet, currentUser } from "@/lib/api";
import { language, label } from "@/lib/language";
import { CATEGORIES, PENDING_CATEGORY, digits, groupByCategory, jalali } from "@/lib/reader";

export const metadata = { title: "News radar · News Intelligence" };
export const dynamic = "force-dynamic";

const PERIODS = [["now", "Last 24h", "۲۴ ساعت اخیر"], ["today", "Today", "امروز"], ["week", "This week", "این هفته"]];
const ORDERS = [["ranked", "Most important", "مهم‌ترین"], ["latest", "Latest first", "تازه‌ترین"]];

/** Sources that crawled successfully in the last six hours, as the release gate counts them. */
async function coverage() {
  try {
    const { results } = await apiGet("/api/public/sources/");
    const fresh = Date.now() - 6 * 3600 * 1000;
    const healthy = results.filter((row) => row.health === "healthy" && Date.parse(row.last_success_at) >= fresh).length;
    return { total: results.length, healthy };
  } catch {
    return null;
  }
}

function Segmented({ label: name, items, current, href, lang }) {
  return <nav aria-label={name} className="inline-flex rounded-full border border-line bg-card p-1 text-sm">
    {items.map(([key, en, fa]) => <Link key={key} href={href(key)} aria-current={current === key ? "page" : undefined}
      className={`rounded-full px-3.5 py-1.5 transition focus-visible:outline-2 focus-visible:outline-accent ${current === key ? "bg-accent-strong font-semibold text-white" : "text-muted hover:text-ink"}`}>
      {label(lang, en, fa)}
    </Link>)}
  </nav>;
}

export default async function NewsHome({ searchParams }) {
  const params = await searchParams;
  const period = PERIODS.some(([key]) => key === params?.period) ? params.period : "now";
  const order = params?.order === "latest" ? "latest" : "ranked";
  const lang = await language();
  const tr = (en, fa) => label(lang, en, fa);
  const [data, alertConfig, user, sources] = await Promise.all([
    apiGet(`/api/public/events/?period=${period}&mode=${order}`),
    apiGet("/api/public/alert-config/"), currentUser(), coverage(),
  ]);
  // An empty window still shows the newest reports rather than a blank page.
  const fallback = data.results.length ? null : await apiGet("/api/public/events/?period=latest&mode=latest");
  const events = (fallback || data).results;
  const [lead, ...rest] = events;
  const sections = groupByCategory(rest);
  const anyAssessed = events.some((event) => event.status !== "developing");
  const href = (next) => {
    const merged = { period, order, ...next };
    const search = new URLSearchParams();
    if (merged.period !== "now") search.set("period", merged.period);
    if (merged.order !== "ranked") search.set("order", merged.order);
    return search.size ? `/?${search}` : "/";
  };

  return <div className="space-y-8">
    <header className="space-y-5">
      <div className="flex flex-wrap items-end justify-between gap-4">
        <div>
          <p className="text-sm font-medium text-accent">{jalali(data.as_of, lang, { time: false })}</p>
          <h1 className="mt-1 text-3xl font-extrabold tracking-tight sm:text-4xl">{tr("News radar", "رادار خبر")}</h1>
          <p className="mt-2 max-w-xl text-sm leading-7 text-muted">{tr(
            "Economic and geopolitical events that may move Iranian markets, ranked by impact and freshness.",
            "رویدادهای اقتصادی و ژئوپلیتیکی که ممکن است بر بازارهای ایران اثر بگذارند؛ به ترتیب اهمیت و تازگی.")}</p>
        </div>
        <div className="flex flex-wrap gap-2">
          <Segmented label={tr("Time window", "بازهٔ زمانی")} items={PERIODS} current={period} lang={lang} href={(key) => href({ period: key })} />
          <Segmented label={tr("Order", "ترتیب")} items={ORDERS} current={order} lang={lang} href={(key) => href({ order: key })} />
        </div>
      </div>
      {sources && sources.total && sources.healthy < sources.total ? <p role="status" className="flex items-start gap-2 rounded-xl border border-line bg-card-2 px-4 py-3 text-sm leading-7 text-muted">
        <Icon name="info" className="mt-1 h-4 w-4 shrink-0" />
        {tr(`Coverage is limited right now: ${digits(sources.healthy, lang)} of ${digits(sources.total, lang)} sources reported in the last six hours. Some events may appear later.`,
          `پوشش خبری فعلاً محدود است: ${digits(sources.healthy, lang)} از ${digits(sources.total, lang)} منبع در شش ساعت گذشته به‌روز شده‌اند. برخی رویدادها ممکن است دیرتر نمایش داده شوند.`)}
      </p> : null}
      {fallback && events.length ? <p role="status" className="rounded-xl border border-line bg-card-2 px-4 py-3 text-sm text-muted">
        {tr("Nothing new in this window yet - showing the most recent reports.", "در این بازه هنوز خبری نیست؛ تازه‌ترین گزارش‌ها نمایش داده می‌شوند.")}
      </p> : null}
      {events.length && !anyAssessed ? <p role="status" className="rounded-xl border border-line bg-card-2 px-4 py-3 text-sm text-muted">
        {tr("Assessments are still running - these are developing reports.", "ارزیابی‌ها هنوز در جریان است؛ این‌ها گزارش‌های در حال تکمیل‌اند.")}
      </p> : null}
    </header>

    {lead ? <section aria-label={tr("Top story", "خبر اصلی")}><EventTile event={lead} lang={lang} variant="hero" /></section>
      : <div className="rounded-2xl border border-dashed border-line p-12 text-center text-muted">
        <Icon name="radar" className="mx-auto mb-3 h-10 w-10" />
        {tr("No events yet. The radar refreshes as sources report.", "هنوز رویدادی ثبت نشده است. رادار با رسیدن خبرها به‌روز می‌شود.")}
      </div>}

    {sections.length > 1 ? <nav aria-label={tr("Categories", "دسته‌ها")} className="-mx-3 flex gap-2 overflow-x-auto px-3 pb-1 sm:mx-0 sm:flex-wrap sm:px-0">
      {sections.map(({ key, items }) => {
        const meta = CATEGORIES[key] || PENDING_CATEGORY;
        return <a key={key} href={`#cat-${key}`} className="inline-flex shrink-0 items-center gap-2 rounded-full border border-line bg-card px-3.5 py-1.5 text-sm hover:border-accent focus-visible:outline-2 focus-visible:outline-accent">
          <span className={`art-${key} flex h-6 w-6 items-center justify-center rounded-full text-white`}><Icon name={meta.icon} className="h-3.5 w-3.5" /></span>
          {meta[lang]} <span className="text-muted">{digits(items.length, lang)}</span>
        </a>;
      })}
    </nav> : null}

    {/* Small categories pack side by side on wider screens instead of leaving a lone card
        in a three-column row; a busy category takes the full width. */}
    <div className="grid grid-flow-row-dense gap-x-4 gap-y-10 sm:grid-cols-2 lg:grid-cols-3">
      {sections.map(({ key, items }) => {
        const meta = CATEGORIES[key] || PENDING_CATEGORY;
        const span = items.length >= 3 ? "sm:col-span-2 lg:col-span-3" : items.length === 2 ? "sm:col-span-2" : "";
        const columns = items.length >= 3 ? "sm:grid-cols-2 lg:grid-cols-3" : items.length === 2 ? "sm:grid-cols-2" : "";
        return <section key={key} id={`cat-${key}`} aria-labelledby={`cat-${key}-title`} className={`scroll-mt-24 space-y-4 ${span}`}>
          <h2 id={`cat-${key}-title`} className="flex items-center gap-3 text-xl font-bold">
            <span className={`art-${key} flex h-9 w-9 items-center justify-center rounded-xl text-white`}><Icon name={meta.icon} /></span>
            {meta[lang]}
            <span className="text-sm font-normal text-muted">{digits(items.length, lang)} {tr(items.length === 1 ? "event" : "events", "رویداد")}</span>
          </h2>
          <div className={`grid gap-4 ${columns}`}>
            {items.map((event, index) => <EventTile key={event.id} event={event} lang={lang} variant={index ? "compact" : "card"} />)}
          </div>
        </section>;
      })}
    </div>

    <AlertOptIn publicKey={alertConfig.public_key} signedIn={Boolean(user)} lang={lang} />
  </div>;
}
