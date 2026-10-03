import Link from "next/link";
import EventImage from "@/components/EventImage";
import { CategoryChip, Icon, StatusBadge, TierBadge, WatchChips, When } from "@/components/reader";
import { language, label } from "@/lib/language";
import { loadEvent, loadTakedown } from "./load";
import TakedownControl from "./TakedownControl";
import { EVIDENCE, STANCE, digits, groupSources, headline, leadSource, sep, tierMeta } from "@/lib/reader";

export const dynamic = "force-dynamic";

function Block({ title, icon, children }) {
  return <section className="rounded-2xl border border-line bg-card p-5 sm:p-6">
    <h2 className="mb-3 flex items-center gap-2 text-lg font-bold"><Icon name={icon} className="h-5 w-5 text-accent" />{title}</h2>
    {children}
  </section>;
}

export default async function EventDetail({ params }) {
  const { id } = await params;
  const takedown = await loadTakedown(id);
  const event = await loadEvent(id, { allowMissing: Boolean(takedown) });
  const lang = await language();
  if (!event) {
    return <article className="mx-auto max-w-3xl space-y-4">
      <p className="rounded-2xl border border-dashed border-line p-4 text-sm text-muted">{lang === "fa" ? "از دید خوانندگان پنهان است." : "Hidden from readers."}</p>
      <TakedownControl state={takedown} />
    </article>;
  }
  const tr = (en, fa) => label(lang, en, fa);
  const pick = (field) => event[`${field}_${lang}`];
  const title = headline(event, lang);
  const primaryName = leadSource(event)?.name || null;
  const image = event.image_large_url || event.image_url;
  const photoBy = event.image_source || primaryName;
  const assessed = tierMeta(event.iran_tier) || tierMeta(event.global_tier);
  const groups = groupSources(event.sources);

  return <article className="mx-auto max-w-3xl space-y-6">
    <nav className="flex items-center justify-between gap-3 text-sm">
      <Link href="/" className="inline-flex items-center gap-1 text-accent hover:underline">
        <Icon name="arrow" className="h-4 w-4 rotate-180 rtl:rotate-0" />{tr("News radar", "رادار خبر")}
      </Link>
      <CategoryChip category={event.category} lang={lang} className="text-muted" />
    </nav>

    <header className="space-y-4">
      {/* Only a photo we may republish gets a frame; no 16:9 placeholder above the headline. */}
      {image ? <figure className="overflow-hidden rounded-2xl border border-line bg-card">
        <EventImage src={image} category={event.category} eager
          alt={photoBy ? tr(`Photo published by ${photoBy}`, `تصویر منتشرشده در ${photoBy}`) : ""}
          className="aspect-[16/9] w-full" />
      </figure> : null}
      <h1 className="text-2xl font-extrabold leading-snug sm:text-4xl sm:leading-tight" dir="auto">{title}</h1>
      {title !== event.original_title ? <p className="text-sm text-muted" dir="auto">{event.original_title}</p> : null}
      <div className="flex flex-wrap items-center gap-x-3 gap-y-2 text-sm text-muted">
        {primaryName ? <span className="font-semibold text-ink">{primaryName}</span> : null}
        <When iso={event.event_time} lang={lang} time />
        {event.status !== "developing" ? <StatusBadge status={event.status} lang={lang} /> : null}
        {EVIDENCE[event.evidence_level] ? <span className="rounded-full border border-line px-2.5 py-0.5 text-xs">{EVIDENCE[event.evidence_level][lang]}</span> : null}
      </div>
      <div className={`grid gap-3 rounded-2xl border border-line bg-card p-4 sm:items-center ${assessed ? "sm:grid-cols-[1fr_1fr_auto]" : "sm:grid-cols-[1fr_auto]"}`}>
        {assessed ? <>
          <div className="space-y-1"><p className="text-xs text-muted">{tr("Relevance for Iran", "اهمیت برای ایران")}</p><TierBadge tier={event.iran_tier} lang={lang} prefix={false} /></div>
          <div className="space-y-1"><p className="text-xs text-muted">{tr("Global significance", "اهمیت جهانی")}</p><TierBadge tier={event.global_tier} lang={lang} prefix={false} /></div>
        </> : <p className="flex items-center gap-2 text-sm text-muted">
          <span className="h-2 w-2 shrink-0 rounded-full bg-current motion-safe:animate-pulse" aria-hidden="true" />
          {tr("Impact for Iran and globally is still being assessed.", "اثر این رویداد بر ایران و جهان در حال ارزیابی است.")}
        </p>}
        <Link href={`/events/${event.id}/market`} className="inline-flex items-center justify-center gap-2 rounded-xl bg-accent-strong px-4 py-3 font-semibold text-white hover:opacity-90 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent">
          <Icon name="candles" />{tr("Market impact", "اثر بر بازار")}
        </Link>
      </div>
      <WatchChips items={event.watch_items} lang={lang} />
    </header>

    {pick("brief") ? <Block title={tr("What happened", "چه اتفاقی افتاد")} icon="layers">
      <p className="leading-8" dir="auto">{pick("brief")}</p>
    </Block> : <p className="flex items-center gap-2 rounded-2xl border border-dashed border-line p-4 text-sm text-muted">
      <Icon name="radar" className="h-4 w-4" />{tr("Developing: the summary is still being prepared.", "در حال تکمیل: خلاصهٔ این رویداد هنوز آماده نشده است.")}
    </p>}
    {pick("channels") ? <Block title={tr("Why it may matter", "چرا ممکن است مهم باشد")} icon="chart">
      <p className="leading-8 text-ink" dir="auto">{pick("channels")}</p>
    </Block> : null}
    {pick("uncertainty") ? <Block title={tr("What is still unclear", "آنچه هنوز روشن نیست")} icon="info">
      <p className="leading-8 text-muted" dir="auto">{pick("uncertainty")}</p>
    </Block> : null}
    <p className="text-xs leading-6 text-muted">{tr("Impact is an assessment, not a forecast or proof of a price effect.", "میزان اثر یک ارزیابی است؛ پیش‌بینی یا اثبات اثر بر قیمت نیست.")}</p>

    <section aria-labelledby="sources-title" className="space-y-3">
      <h2 id="sources-title" className="text-xl font-bold">{tr("Sources", "منابع")}
        <span className="ms-2 text-sm font-normal text-muted">{tr(`${groups.length} independent groups · ${event.sources.length} reports`, `${digits(groups.length, lang)} گروه مستقل، ${digits(event.sources.length, lang)} گزارش`)}</span>
      </h2>
      <div className="grid gap-3">{groups.map((group) => <div key={group.key} className="rounded-2xl border border-line bg-card p-4">
        <h3 className="mb-2 flex items-center justify-between gap-2 font-semibold" dir="auto">{group.name}
          <span className="flex shrink-0 items-center gap-2">
            {group.disputes ? <span className="tier-5 rounded-full px-2 py-0.5 text-xs font-semibold">{tr("Disputes this account", "روایت متفاوت")}</span> : null}
            <span className="rounded-full bg-card-2 px-2 py-0.5 text-xs font-normal text-muted">{digits(group.items.length, lang)} {tr("reports", "گزارش")}</span>
          </span>
        </h3>
        <ul className="divide-y divide-line">{group.items.map((source) => <li key={source.url} className="py-2">
          <a href={source.url} target="_blank" rel="noopener noreferrer" className="font-medium text-accent hover:underline" dir="auto">{source.headline || source.url}</a>
          <p className="mt-1 flex flex-wrap items-center gap-x-2 text-xs text-muted">
            {group.items.length > 1 || source.name !== group.name ? <span>{source.original_outlet || source.name}</span> : null}
            <When iso={source.published_at || source.first_seen_at} lang={lang} time showRelative={false} />
            {source.date_uncertain ? tr(" · date uncertain", "، تاریخ نامطمئن") : ""}
            {source.stance && source.stance !== "reports" && STANCE[source.stance] ? <span className={`rounded-full px-2 py-0.5 ${source.stance === "contradicts" ? "tier-5 font-semibold" : "border border-line"}`}>{STANCE[source.stance][lang]}</span> : null}
          </p>
          {source.lead ? <p className="mt-1 line-clamp-3 text-sm leading-7 text-muted" dir="auto">{source.lead}</p> : null}
        </li>)}</ul>
      </div>)}</div>
    </section>

    {takedown ? <TakedownControl state={takedown} /> : null}

    <section aria-labelledby="story-title" className="space-y-3">
      <h2 id="story-title" className="text-xl font-bold">{tr("Storyline", "روند رویداد")}</h2>
      {event.storyline ? <div className="rounded-2xl border border-line bg-card p-4">
        <p className="mb-2 font-semibold" dir="auto">{(lang === "en" && event.storyline.name_en) || event.storyline.name_fa}</p>
        <ol className="space-y-2 border-s border-line ps-4 text-sm">{event.storyline.events.map((item) => <li key={item.id}>
          <p className="text-xs text-muted"><When iso={item.event_time} lang={lang} showRelative={false} /></p>
          {item.id === event.id
            ? <p className="font-semibold" dir="auto" aria-current="page">{(lang === "en" && item.title_en) || item.title_fa}</p>
            : <Link href={`/events/${item.id}`} className="text-accent hover:underline" dir="auto">{(lang === "en" && item.title_en) || item.title_fa}</Link>}
        </li>)}</ol>
      </div> : <p className="rounded-2xl border border-dashed border-line p-4 text-sm text-muted">{tr("Related events will appear here once this story develops.", "رویدادهای مرتبط پس از ادامه‌یافتن این خبر اینجا نمایش داده می‌شوند.")}</p>}
      {event.history?.length ? <>
        <h3 className="pt-2 font-semibold">{tr("Earlier versions of these reports", "نسخه‌های پیشین این گزارش‌ها")}</h3>
        <ul className="space-y-2 text-sm">{event.history.map((change, index) =>
          <li key={`${change.observed_at}-${index}`} className="rounded-xl border border-line bg-card p-3">
            <p className="text-xs text-muted">{change.source}{sep(lang)}<When iso={change.observed_at} lang={lang} time showRelative={false} />{sep(lang)}{change.previous_status}</p>
            <p className="mt-1" dir="auto">{change.previous_headline}</p>
          </li>)}</ul>
      </> : null}
    </section>
  </article>;
}
