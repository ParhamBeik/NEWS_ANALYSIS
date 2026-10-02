import { CATEGORIES, PENDING_CATEGORY, STATUS, gregorian, jalali, tierMeta, relative, sep } from "@/lib/reader";

const ICONS = {
  bank: "M3 10h18M5 10v8M9.5 10v8M14.5 10v8M19 10v8M3 20h18M12 3l9 5H3z",
  chart: "M4 20V11M10 20V5M16 20v-6M3 20h18",
  ship: "M3 15h18l-2.5 5h-13zM6 15V9h5v6M11 11h5v4",
  globe: "M12 3a9 9 0 1 0 0 18a9 9 0 1 0 0-18zM3 12h18M12 3c3.5 3.5 3.5 14.5 0 18M12 3c-3.5 3.5-3.5 14.5 0 18",
  flame: "M12 3c1 4 5 6 5 11a5 5 0 0 1-10 0c0-3 2-4 2-7 2 1 3 3 3 5 1-2 0-6 0-9z",
  candles: "M7 3v18M5 7h4v9H5zM17 3v18M15 5h4v7h-4z",
  radar: "M12 3a9 9 0 1 0 0 18a9 9 0 1 0 0-18zM12 7a5 5 0 1 0 0 10a5 5 0 1 0 0-10zM12 12l6-6",
  info: "M12 3a9 9 0 1 0 0 18a9 9 0 1 0 0-18zM12 11v5M12 7.5v.5",
  check: "M5 12.5l4.5 4.5L19 7.5",
  star: "M12 3.5l2.6 5.3 5.9.9-4.3 4.1 1 5.8-5.2-2.7-5.2 2.7 1-5.8-4.3-4.1 5.9-.9z",
  bell: "M6 16V11a6 6 0 0 1 12 0v5l2 2H4zM10 20a2 2 0 0 0 4 0",
  arrow: "M5 12h14M13 6l6 6-6 6",
  layers: "M12 3l9 5-9 5-9-5zM3 13l9 5 9-5",
  shield: "M12 3l8 3v6c0 4.5-3.4 8-8 9-4.6-1-8-4.5-8-9V6z",
  wave: "M3 12h3l2-5 3 10 3-8 2 3h5",
  people: "M9 11a3 3 0 1 0 0-6a3 3 0 1 0 0 6zM3 20c0-3.3 2.7-6 6-6s6 2.7 6 6M16 5.5a3 3 0 0 1 0 5.5M18 14.5c1.8.8 3 2.8 3 5.5",
};

export function Icon({ name, className = "h-5 w-5" }) {
  return <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round"
    strokeLinejoin="round" className={className} aria-hidden="true" focusable="false">
    <path d={ICONS[name] || ICONS.radar} />
  </svg>;
}

export function CategoryChip({ category, lang, className = "" }) {
  const meta = CATEGORIES[category] || PENDING_CATEGORY;
  return <span className={`inline-flex items-center gap-1.5 text-xs font-semibold ${className}`}>
    <Icon name={meta.icon} className="h-4 w-4" />{meta[lang]}
  </span>;
}

/** Jev's watch-item tags (assets, actors, themes) as quiet chips; not links yet. */
export function WatchChips({ items, lang, limit = 5, className = "" }) {
  if (!items?.length) return null;
  return <ul aria-label={lang === "fa" ? "موضوع‌های مرتبط" : "Related watch items"} className={`flex flex-wrap gap-1.5 ${className}`}>
    {items.slice(0, limit).map((item) => <li key={item.slug} className="rounded-full border border-line bg-card-2 px-2 py-0.5 text-xs text-muted">
      {lang === "fa" ? item.name_fa : item.name_en}
    </li>)}
  </ul>;
}

function Meter({ level }) {
  return <span className="inline-flex items-end gap-[2px]" aria-hidden="true">
    {[1, 2, 3, 4, 5].map((step) => <span key={step} className="w-[3px] rounded-sm bg-current"
      style={{ height: `${4 + step * 2}px`, opacity: step <= level ? 1 : 0.3 }} />)}
  </span>;
}

/** Impact tier from the API: one hue, five intensities, plus a five-step meter so colour is
 *  never the only cue. */
export function TierBadge({ tier: level, lang, prefix = true }) {
  const tier = tierMeta(level);
  if (!tier) {
    return <span className="inline-flex items-center rounded-full border border-dashed border-line px-2.5 py-0.5 text-xs text-muted">
      {lang === "fa" ? "اثر هنوز ارزیابی نشده" : "Impact not assessed yet"}
    </span>;
  }
  const text = lang === "fa" ? `${prefix ? "اثر " : ""}${tier.fa}` : `${tier.en}${prefix ? " impact" : ""}`;
  return <span className={`tier-${tier.level} inline-flex items-center gap-1.5 rounded-full px-2.5 py-0.5 text-xs font-semibold`}>
    <Meter level={tier.level} />{text}
  </span>;
}

export function StatusBadge({ status, lang }) {
  const meta = STATUS[status];
  if (!meta) return null;
  if (meta.tone === "pending") {
    return <span className="inline-flex items-center gap-1.5 rounded-full border border-dashed border-line px-2.5 py-0.5 text-xs text-muted">
      <span className="h-1.5 w-1.5 rounded-full bg-current motion-safe:animate-pulse" aria-hidden="true" />{meta[lang]}
    </span>;
  }
  return <span className="inline-flex items-center gap-1 rounded-full border border-line px-2.5 py-0.5 text-xs text-ink">
    <Icon name="check" className="h-3.5 w-3.5" />{meta[lang]}
  </span>;
}

/** Relative time plus the Jalali date; Gregorian on hover. */
export function When({ iso, lang, time = false, showRelative = true, className = "" }) {
  if (!iso) return null;
  return <time dateTime={iso} title={gregorian(iso)} className={className}>
    {showRelative ? `${relative(iso, lang)}${sep(lang)}` : ""}{jalali(iso, lang, { time })}
  </time>;
}
