import Link from "next/link";
import EventImage from "@/components/EventImage";
import { CategoryChip, Icon, StatusBadge, TierBadge, When } from "@/components/reader";
import { language, label } from "@/lib/language";
import { loadEvent } from "./load";
import { digits, groupSources, headline, sep } from "@/lib/reader";

export const dynamic = "force-dynamic";

function Block({ title, icon, children }) {
  return <section className="rounded-2xl border border-line bg-card p-5 sm:p-6">
    <h2 className="mb-3 flex items-center gap-2 text-lg font-bold"><Icon name={icon} className="h-5 w-5 text-accent" />{title}</h2>
    {children}
  </section>;
}

export default async function EventDetail({ params }) {
  const { id } = await params;
  const event = await loadEvent(id);
  const lang = await language();
  const tr = (en, fa) => label(lang, en, fa);
  const pick = (field) => event[`${field}_${lang}`];
  const title = headline(event, lang);
  const primary = event.sources.find((source) => source.headline === event.original_title) || event.sources[0];
  const primaryName = primary ? primary.original_outlet || primary.name : null;
  const groups = groupSources(event.sources);

  return <article className="mx-auto max-w-3xl space-y-6">
    <nav className="flex items-center justify-between gap-3 text-sm">
      <Link href="/" className="inline-flex items-center gap-1 text-accent hover:underline">
        <Icon name="arrow" className="h-4 w-4 rotate-180 rtl:rotate-0" />{tr("News radar", "رادار خبر")}
      </Link>
      <CategoryChip category={event.category} lang={lang} className="text-muted" />
    </nav>

    <header className="space-y-4">
      <figure className="overflow-hidden rounded-2xl border border-line bg-card">
        <EventImage src={event.image_large_url || event.image_url} category={event.category} eager
          alt={primaryName ? tr(`Photo published by ${primaryName}`, `تصویر منتشرشده در ${primaryName}`) : ""}
          className="aspect-[16/9] w-full" />
      </figure>
      <h1 className="text-2xl font-extrabold leading-snug sm:text-4xl sm:leading-tight" dir="auto">{title}</h1>
      {title !== event.original_title ? <p className="text-sm text-muted" dir="auto">{event.original_title}</p> : null}
      <div className="flex flex-wrap items-center gap-x-3 gap-y-2 text-sm text-muted">
        {primaryName ? <span className="font-semibold text-ink">{primaryName}</span> : null}
        <When iso={event.event_time} lang={lang} time />
        <StatusBadge status={event.status} lang={lang} />
      </div>
      <div className="grid gap-3 rounded-2xl border border-line bg-card p-4 sm:grid-cols-[1fr_1fr_auto] sm:items-center">
        <div className="space-y-1"><p className="text-xs text-muted">{tr("Relevance for Iran", "اهمیت برای ایران")}</p><TierBadge score={event.iran_score} lang={lang} prefix={false} /></div>
        <div className="space-y-1"><p className="text-xs text-muted">{tr("Global significance", "اهمیت جهانی")}</p><TierBadge score={event.global_score} lang={lang} prefix={false} /></div>
        <Link href={`/events/${event.id}/market`} className="inline-flex items-center justify-center gap-2 rounded-xl bg-accent-strong px-4 py-3 font-semibold text-white hover:opacity-90 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent">
          <Icon name="candles" />{tr("Market impact", "اثر بر بازار")}
        </Link>
      </div>
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
        <span className="ms-2 text-sm font-normal text-muted">{tr(`${groups.length} outlets · ${event.sources.length} reports`, `${digits(groups.length, lang)} رسانه، ${digits(event.sources.length, lang)} گزارش`)}</span>
      </h2>
      {/* TODO(reader): group by independence (official / state / private / international) once
          the API exposes it; Source has no such field yet, so this groups by outlet. */}
      <div className="grid gap-3">{groups.map((group) => <div key={group.name} className="rounded-2xl border border-line bg-card p-4">
        <h3 className="mb-2 flex items-center justify-between gap-2 font-semibold">{group.name}
          <span className="rounded-full bg-card-2 px-2 py-0.5 text-xs font-normal text-muted">{digits(group.items.length, lang)} {tr("reports", "گزارش")}</span>
        </h3>
        <ul className="divide-y divide-line">{group.items.map((source) => <li key={source.url} className="py-2">
          <a href={source.url} target="_blank" rel="noopener noreferrer" className="font-medium text-accent hover:underline" dir="auto">{source.headline || source.url}</a>
          <p className="mt-1 text-xs text-muted"><When iso={source.published_at || source.first_seen_at} lang={lang} time showRelative={false} />
            {source.date_uncertain ? tr(" · date uncertain", "، تاریخ نامطمئن") : ""}</p>
          {source.lead ? <p className="mt-1 line-clamp-3 text-sm leading-7 text-muted" dir="auto">{source.lead}</p> : null}
        </li>)}</ul>
      </div>)}</div>
    </section>

    <section aria-labelledby="story-title" className="space-y-3">
      <h2 id="story-title" className="text-xl font-bold">{tr("Storyline", "روند رویداد")}</h2>
      {event.history?.length ? <ul className="space-y-2 text-sm">{event.history.map((change, index) =>
        <li key={`${change.observed_at}-${index}`} className="rounded-xl border border-line bg-card p-3">
          <p className="text-xs text-muted">{change.source}{sep(lang)}<When iso={change.observed_at} lang={lang} time showRelative={false} />{sep(lang)}{change.previous_status}</p>
          <p className="mt-1" dir="auto">{change.previous_headline}</p>
        </li>)}</ul>
        : <p className="rounded-2xl border border-dashed border-line p-4 text-sm text-muted">{tr("Related events and earlier chapters of this story will appear here.", "رویدادهای مرتبط و مراحل پیشین این خبر به‌زودی اینجا نمایش داده می‌شوند.")}</p>}
    </section>
  </article>;
}
