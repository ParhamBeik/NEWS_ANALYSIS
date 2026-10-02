import Link from "next/link";
import EventImage from "@/components/EventImage";
import { CategoryChip, StatusBadge, TierBadge, WatchChips, When } from "@/components/reader";
import { digits, headline, impactScore, sourceCount, whyItMatters } from "@/lib/reader";

function Meta({ event, lang }) {
  const count = sourceCount(event);
  return <div className="flex flex-wrap items-center gap-x-3 gap-y-1 text-xs text-muted">
    <When iso={event.event_time} lang={lang} />
    <span>{digits(count, lang)} {lang === "fa" ? "منبع" : count === 1 ? "source" : "sources"}</span>
  </div>;
}

/**
 * One event on the radar. The headline link is stretched over the whole card, so the card
 * is a single tab stop and the focus ring is drawn on the card itself.
 *
 * `hero` is the lead story; `compact` turns a card into an image-beside-text row on phones.
 */
export default function EventTile({ event, lang, variant = "card" }) {
  const title = headline(event, lang);
  const why = whyItMatters(event, lang);
  const hero = variant === "hero";
  const compact = variant === "compact";
  const shell = "group relative overflow-hidden rounded-2xl border border-line bg-card shadow-sm transition has-[a:focus-visible]:outline-2 has-[a:focus-visible]:outline-offset-2 has-[a:focus-visible]:outline-accent motion-safe:hover:-translate-y-0.5 hover:shadow-md";
  const image = event.image_large_url && hero ? event.image_large_url : event.image_url;
  return <article className={`${shell} ${hero ? "md:grid md:grid-cols-5" : compact ? "flex sm:block" : ""}`}>
    <div className={`relative overflow-hidden ${hero ? "aspect-[16/10] md:col-span-3 md:aspect-auto md:min-h-80" : compact ? "w-28 shrink-0 sm:w-auto sm:aspect-[16/9]" : "aspect-[16/9]"}`}>
      <EventImage src={image} category={event.category} eager={hero}
        className="h-full w-full motion-safe:transition-transform motion-safe:duration-500 motion-safe:group-hover:scale-[1.03]" />
      {!compact ? <span className="absolute start-3 top-3 rounded-full bg-black/60 px-2.5 py-1 text-white backdrop-blur-sm">
        <CategoryChip category={event.category} lang={lang} />
      </span> : null}
    </div>
    <div className={`flex min-w-0 flex-col gap-2.5 ${hero ? "p-5 md:col-span-2 md:justify-center md:p-7" : compact ? "p-3 sm:p-4" : "p-4"}`}>
      <div className="flex flex-wrap items-center gap-2">
        <TierBadge score={impactScore(event)} lang={lang} />
        <StatusBadge status={event.status} lang={lang} />
      </div>
      <h3 className={`font-bold text-ink ${hero ? "text-2xl leading-snug md:text-3xl" : compact ? "line-clamp-3 text-[15px] leading-7 sm:text-base" : "text-lg leading-8"}`} dir="auto">
        <Link href={`/events/${event.id}`} className="outline-none after:absolute after:inset-0 hover:text-accent">{title}</Link>
      </h3>
      {why ? <p className={`text-sm leading-7 text-muted ${hero ? "line-clamp-3 md:text-base md:leading-8" : compact ? "hidden sm:line-clamp-1" : "line-clamp-1"}`} dir="auto">
        <span className="sr-only">{lang === "fa" ? "چرا مهم است: " : "Why it may matter: "}</span>{why}
      </p> : null}
      <WatchChips items={event.watch_items} lang={lang} limit={compact ? 3 : 5} className={compact ? "hidden sm:flex" : ""} />
      <Meta event={event} lang={lang} />
    </div>
  </article>;
}
