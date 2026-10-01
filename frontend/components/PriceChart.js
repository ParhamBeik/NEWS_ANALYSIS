import { chartGeometry, digits, jalali } from "@/lib/reader";

const W = 640;
const H = 240;
const PAD = 12;

function price(value, lang) {
  const rounded = Math.abs(value) >= 1000 ? Math.round(value) : Math.round(value * 100) / 100;
  return digits(rounded, lang);
}

/**
 * One price series with a vertical marker at the event. Server-rendered: no chart library
 * reaches the phone, and the line is neutral - no red/green judgement on a move.
 * The SVG stretches to its box and draws only lines; labels are HTML so they stay legible
 * at phone width and keep their own text direction.
 */
export default function PriceChart({ points, start, end, eventTime, lang, assetName }) {
  const geometry = chartGeometry(points, { start, end, width: W, height: H, pad: PAD });
  if (!geometry) return null;
  const { path, low, high, x, first, last } = geometry;
  const marker = new Date(eventTime).getTime();
  const at = marker >= start && marker <= end ? (x(marker) / W) * 100 : null;
  const date = (time) => jalali(time, lang, { time: false });
  const summary = lang === "fa"
    ? `${assetName}: از ${price(first[1], lang)} در ${date(first[0])} تا ${price(last[1], lang)} در ${date(last[0])}؛ کمینه ${price(low, lang)}، بیشینه ${price(high, lang)}.`
    : `${assetName}: from ${price(first[1], lang)} on ${date(first[0])} to ${price(last[1], lang)} on ${date(last[0])}; low ${price(low, lang)}, high ${price(high, lang)}.`;
  const edge = at === null ? null : at < 22 ? "start" : at > 78 ? "end" : null;
  return <figure dir="ltr" className="select-none" role="img" aria-label={summary}>
    <div className="relative h-56 sm:h-72">
      <svg viewBox={`0 0 ${W} ${H}`} preserveAspectRatio="none" className="absolute inset-0 h-full w-full" aria-hidden="true">
        <defs>
          <linearGradient id="price-fill" x1="0" x2="0" y1="0" y2="1">
            <stop offset="0" stopColor="var(--price-line)" stopOpacity="0.16" />
            <stop offset="1" stopColor="var(--price-line)" stopOpacity="0" />
          </linearGradient>
        </defs>
        {[PAD, H / 2, H - PAD].map((y) => <line key={y} x1="0" x2={W} y1={y} y2={y} stroke="var(--line)" strokeDasharray="3 5" vectorEffect="non-scaling-stroke" />)}
        <path d={`${path} L${x(last[0]).toFixed(1)},${H} L${x(first[0]).toFixed(1)},${H} Z`} fill="url(#price-fill)" />
        <path d={path} fill="none" stroke="var(--price-line)" strokeWidth="2.2" strokeLinejoin="round" strokeLinecap="round" vectorEffect="non-scaling-stroke" />
        {at !== null ? <line x1={x(marker)} x2={x(marker)} y1="0" y2={H} stroke="var(--accent)" strokeWidth="2" strokeDasharray="5 4" vectorEffect="non-scaling-stroke" /> : null}
      </svg>
      {at !== null ? <span className="absolute top-0 h-3 w-3 -translate-x-1/2 rounded-full bg-accent ring-4 ring-card" style={{ left: `${at}%` }} aria-hidden="true" /> : null}
      <span className="absolute left-1 top-1 rounded bg-card/80 px-1 text-xs text-muted tabular">{price(high, lang)}</span>
      <span className="absolute bottom-1 left-1 rounded bg-card/80 px-1 text-xs text-muted tabular">{price(low, lang)}</span>
    </div>
    <div className="relative mt-2 flex h-5 justify-between text-xs text-muted" aria-hidden="true">
      <span dir="auto" className={edge === "start" ? "invisible" : ""}>{date(start)}</span>
      <span dir="auto" className={edge === "end" ? "invisible" : ""}>{date(end)}</span>
      {at !== null ? <span className={`absolute top-0 whitespace-nowrap font-bold text-accent ${edge === "start" ? "" : edge === "end" ? "-translate-x-full" : "-translate-x-1/2"}`}
        style={{ left: `${at}%` }}>{lang === "fa" ? "زمان رویداد" : "Event"}</span> : null}
    </div>
  </figure>;
}
