import Link from "next/link";
import EventImage from "@/components/EventImage";
import { CategoryChip, Icon, StatusBadge, TierBadge, WatchChips, When } from "@/components/reader";
import { CATEGORIES, digits, headline, leadSource, tierMeta, untranslated, whyItMatters } from "@/lib/reader";

/**
 * One status signal per card, never three. An assessed event shows its impact tier; a
 * withdrawn or corrected one says so; anything else is "being assessed" - and inside the
 * "being assessed" section even that is dropped, because the section heading already said it.
 */
function StatusPill({ event, lang, hidePending }) {
  if (event.status === "withdrawn" || event.status === "corrected") return <StatusBadge status={event.status} lang={lang} />;
  if (tierMeta(event.impact_tier)) return <TierBadge tier={event.impact_tier} lang={lang} />;
  if (hidePending) return null;
  return <span className="inline-flex items-center gap-1.5 rounded-full border border-dashed border-line px-2.5 py-0.5 text-xs text-muted">
    <span className="h-1.5 w-1.5 rounded-full bg-current motion-safe:animate-pulse" aria-hidden="true" />
    {lang === "fa" ? "در حال ارزیابی" : "Being assessed"}
  </span>;
}

/** Outlet initial in a disc: gives a photo-less card an identity at a glance. */
function Monogram({ name }) {
  const letter = [...(name || "?").replace(/^(the|al)\s+/i, "")][0];
  return <span aria-hidden="true" className="flex h-6 w-6 shrink-0 items-center justify-center rounded-full bg-card-2 text-[11px] font-bold text-ink ring-1 ring-line">
    {letter}
  </span>;
}

/** "ISNA + 2 · 12 minutes ago" - who reported it and when, on one line above the headline. */
function Byline({ event, lang, compact }) {
  const lead = leadSource(event);
  const fa = lang === "fa";
  return <div className="flex min-w-0 items-center gap-2 text-xs text-muted">
    {lead ? <>
      <Monogram name={lead.name} />
      <span className="truncate font-semibold text-ink/90" dir="auto">{lead.name}</span>
      {lead.others ? <span className="shrink-0 rounded-full bg-card-2 px-1.5 leading-5" dir="ltr"
        title={fa ? `${digits(lead.others, lang)} منبع مستقل دیگر` : `${lead.others} more independent outlets`}>+{digits(lead.others, lang)}</span> : null}
      {/* No middle dot: beside Persian digits it reads as a zero (see lib/reader.js sep). */}
      <span aria-hidden="true" className="h-3 w-px shrink-0 bg-line" />
    </> : null}
    <When iso={event.event_time} lang={lang} showRelative className="shrink-0" />
    {untranslated(event, lang) ? <span className="shrink-0 rounded border border-line px-1.5 text-[10px] leading-4">{fa ? "انگلیسی" : "EN"}</span> : null}
  </div>;
}

/**
 * One event on the radar. The headline link is stretched over the whole card, so the card
 * is a single tab stop and the focus ring is drawn on the card itself.
 *
 * `hero` is the lead story; `compact` is a dense row on phones. A card only reserves room for
 * a picture when there is one we may republish (Source.public_image_allowed); otherwise it
 * is a text card with a thin category stripe instead of a large grey placeholder.
 * `inSection` is the category the card is listed under, so the card does not repeat it.
 */
export default function EventTile({ event, lang, variant = "card", inSection = null }) {
  const title = headline(event, lang);
  const why = whyItMatters(event, lang);
  const hero = variant === "hero";
  const compact = variant === "compact";
  const image = event.image_large_url && hero ? event.image_large_url : event.image_url;
  const art = CATEGORIES[event.category] ? event.category : "pending";
  const english = untranslated(event, lang);
  const shell = "group relative overflow-hidden rounded-2xl border border-line bg-card shadow-sm transition has-[a:focus-visible]:outline-2 has-[a:focus-visible]:outline-offset-2 has-[a:focus-visible]:outline-accent motion-safe:hover:-translate-y-0.5 hover:shadow-md";
  const layout = image
    ? hero ? "md:grid md:grid-cols-5" : compact ? "flex sm:block" : ""
    : "";

  const media = image
    ? <div className={`relative overflow-hidden ${hero ? "aspect-[16/9] md:col-span-3 md:aspect-auto md:min-h-80" : compact ? "w-28 shrink-0 sm:aspect-[16/9] sm:w-auto" : "aspect-[16/9]"}`}>
      <EventImage src={image} category={event.category} eager={hero}
        className="h-full w-full motion-safe:transition-transform motion-safe:duration-500 motion-safe:group-hover:scale-[1.03]" />
    </div>
    : <div className={`art-${art} ${hero ? "h-1.5" : "h-1"}`} aria-hidden="true" />;

  return <article className={`${shell} ${layout}`}>
    {media}
    {/* A text hero gets a faint wash of its category colour so the lead story still reads as the lead. */}
    {hero && !image ? <div className={`art-${art} pointer-events-none absolute inset-0 opacity-[0.08]`} aria-hidden="true" /> : null}
    <div className={`relative flex min-w-0 flex-col gap-2.5 ${hero ? image ? "p-5 md:col-span-2 md:justify-center md:p-7" : "p-5 sm:p-8" : compact ? "p-3 sm:p-4" : "p-4"}`}>
      {hero || !inSection ? <CategoryChip category={event.category} lang={lang} className="text-accent" /> : null}
      <Byline event={event} lang={lang} compact={compact} />
      <h3 lang={english ? "en" : undefined} dir="auto"
        className={`font-bold text-ink ${hero ? `${image ? "text-2xl md:text-3xl" : "max-w-4xl text-2xl sm:text-3xl md:text-4xl"} leading-snug` : compact ? "line-clamp-3 text-[15px] leading-7 sm:text-base" : "text-lg leading-8"}`}>
        <Link href={`/events/${event.id}`} className="outline-none after:absolute after:inset-0 hover:text-accent">{title}</Link>
      </h3>
      {why ? <p className={`text-sm leading-7 text-muted ${hero ? "line-clamp-3 max-w-3xl md:text-base md:leading-8" : compact ? "hidden sm:line-clamp-2" : "line-clamp-2"}`} dir="auto">
        <span className="sr-only">{lang === "fa" ? "چرا مهم است: " : "Why it may matter: "}</span>{why}
      </p> : null}
      <div className="flex flex-wrap items-center gap-2">
        <StatusPill event={event} lang={lang} hidePending={inSection === "pending"} />
        {event.watched ? <span className="inline-flex items-center gap-1 rounded-full bg-accent-strong px-2.5 py-0.5 text-xs font-semibold text-white">
          <Icon name="star" className="h-3.5 w-3.5" />{lang === "fa" ? "در فهرست شما" : "On your watchlist"}
        </span> : null}
        <WatchChips items={event.watch_items} lang={lang} limit={compact ? 2 : 3} className={compact ? "hidden sm:flex" : ""} />
      </div>
    </div>
  </article>;
}
