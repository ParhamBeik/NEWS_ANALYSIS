import {
  AXIS_LABEL,
  CATEGORY_LABEL,
  CATEGORY_STYLE,
  LEVEL_STYLE,
  TREND_STYLE,
  UNASSESSED_STYLE,
  levelIndex,
} from "@/lib/display";

/**
 * Presentation primitives shared by every page.
 *
 * The one that matters is `ScoreChip`. A null score renders as a dashed "not assessed"
 * chip in its own colour - never as the lowest level, never as an empty gap. The gap is
 * how a reader stops noticing the difference, and not noticing that difference is what
 * suppressed 488 security alerts in the legacy pipeline.
 */

export function Card({ children, className = "" }) {
  return (
    <div
      className={`rounded-xl border border-slate-800 bg-slate-900/60 ${className}`}
    >
      {children}
    </div>
  );
}

export function SectionTitle({ children, hint }) {
  return (
    <div className="mb-3 flex items-baseline justify-between gap-4">
      <h2 className="text-sm font-semibold uppercase tracking-[0.16em] text-slate-400">
        {children}
      </h2>
      {hint && <span className="text-xs text-slate-500">{hint}</span>}
    </div>
  );
}

export function Metric({ label, value, hint, tone = "" }) {
  return (
    <Card className="p-4">
      <div className="text-xs uppercase tracking-wider text-slate-500">{label}</div>
      <div className={`mt-1 text-2xl font-semibold tabular ${tone}`}>{value}</div>
      {hint && <div className="mt-1 text-xs text-slate-500">{hint}</div>}
    </Card>
  );
}

/**
 * `score` is the API's `{value, label}` object, or null.
 *
 * `bdi` around the Persian value is not decoration: an RTL string sitting inside an LTR
 * line ("Gold price impact زیاد 4/5") reorders visually without isolation, and the reader
 * sees the number attached to the wrong label.
 */
export function ScoreChip({ score, axis }) {
  const assessed = Boolean(score?.value);
  const ordinal = assessed ? levelIndex(score.value) : null;
  return (
    <div className="flex items-center justify-between gap-3 rounded-lg border border-slate-800 bg-slate-950/40 px-3 py-2">
      <span className="text-xs text-slate-400">{AXIS_LABEL[axis] || axis}</span>
      <span
        className={`rounded-md border px-2 py-0.5 text-xs ${
          assessed ? LEVEL_STYLE[score.value] : UNASSESSED_STYLE
        }`}
        title={assessed ? score.label : "The model did not assess this axis"}
      >
        {assessed ? (
          <>
            <bdi className="persian">{score.value}</bdi>
            <span className="ml-2 text-[10px] opacity-70 tabular">{ordinal}/5</span>
          </>
        ) : (
          "not assessed"
        )}
      </span>
    </div>
  );
}

export function CategoryBadge({ category }) {
  if (!category) {
    return (
      <span className="rounded-full border border-dashed border-slate-700 px-2.5 py-0.5 text-xs text-slate-500">
        unclassified
      </span>
    );
  }
  return (
    <span
      className={`rounded-full border px-2.5 py-0.5 text-xs ${
        CATEGORY_STYLE[category] || CATEGORY_STYLE.other
      }`}
    >
      {CATEGORY_LABEL[category] || category}
    </span>
  );
}

export function TrendBadge({ trend }) {
  if (!trend?.value) return null;
  return (
    <span
      className={`rounded-full border border-slate-800 px-2.5 py-0.5 text-xs ${
        TREND_STYLE[trend.value] || "text-slate-400"
      }`}
      title={trend.label}
    >
      <bdi className="persian">{trend.value}</bdi>
    </span>
  );
}

/** The notify verdict AND its reason. A bare badge is unauditable; the reason string is
 *  what lets a reviewer disagree with the rule rather than just with the outcome. */
export function NotifyBadge({ decision, showReason = false }) {
  if (!decision) return null;
  const tone = decision.notify
    ? "border-emerald-800 bg-emerald-950 text-emerald-300"
    : decision.status === "insufficient"
      ? "border-amber-900 bg-amber-950 text-amber-300"
      : "border-slate-700 bg-slate-900 text-slate-400";
  return (
    <span className="inline-flex items-center gap-2">
      <span className={`rounded-full border px-2.5 py-0.5 text-xs ${tone}`}>
        {decision.notify ? "NOTIFY" : decision.status === "insufficient" ? "INSUFFICIENT" : "quiet"}
      </span>
      {showReason && decision.reason && (
        <span className="text-xs text-slate-500">{decision.reason}</span>
      )}
    </span>
  );
}

export function EmptyState({ title, children }) {
  return (
    <Card className="p-10 text-center">
      <p className="text-slate-300">{title}</p>
      {children && <p className="mt-2 text-sm text-slate-500">{children}</p>}
    </Card>
  );
}
