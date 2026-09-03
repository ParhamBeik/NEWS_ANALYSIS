/**
 * Display vocabulary.
 *
 * The Persian values are NEVER translated for display - they are shown as stored, with an
 * English gloss beside them. Translating would mean maintaining a reverse mapping for
 * export, and the two would drift.
 *
 * What this module does map is Persian value -> colour and -> ordinal position, which are
 * presentation facts with no authority over the data.
 */

export const LEVEL_ORDER = ["خیلی کم", "کم", "متوسط", "زیاد", "خیلی زیاد"];

export const LEVEL_STYLE = {
  "خیلی کم": "bg-slate-800 text-slate-400 border-slate-700",
  "کم": "bg-sky-950 text-sky-300 border-sky-900",
  "متوسط": "bg-amber-950 text-amber-300 border-amber-900",
  "زیاد": "bg-orange-950 text-orange-300 border-orange-900",
  "خیلی زیاد": "bg-rose-950 text-rose-300 border-rose-900",
};

// The absence of a score is a first-class state with its own colour, deliberately NOT the
// colour of the lowest level. Rendering "not assessed" as if it were «خیلی کم» is the
// display-layer version of the bug that suppressed every security alert.
export const UNASSESSED_STYLE = "bg-transparent text-slate-500 border-dashed border-slate-700";

export const CATEGORY_LABEL = {
  security: "Security",
  economics: "Economics",
  "security/economics": "Security + Economics",
  other: "Other",
};

export const CATEGORY_STYLE = {
  security: "bg-rose-950 text-rose-300 border-rose-900",
  economics: "bg-emerald-950 text-emerald-300 border-emerald-900",
  "security/economics": "bg-violet-950 text-violet-300 border-violet-900",
  other: "bg-slate-800 text-slate-400 border-slate-700",
};

export const AXIS_LABEL = {
  confidence_occurrence: "Confidence of occurrence",
  gold_price_impact: "Gold price impact",
  security_relevance: "Security relevance",
};

export const TREND_STYLE = {
  "↑": "text-emerald-400",
  "↓": "text-rose-400",
  "خنثی": "text-slate-400",
  "نامطمئن": "text-amber-400",
};

export function levelIndex(value) {
  const index = LEVEL_ORDER.indexOf(value);
  return index === -1 ? null : index + 1;
}

export function money(value, digits = 4) {
  if (value === null || value === undefined) return "—";
  return `$${Number(value).toFixed(digits)}`;
}

export function percent(value, digits = 1) {
  if (value === null || value === undefined) return "—";
  return `${(Number(value) * 100).toFixed(digits)}%`;
}

export function number(value) {
  if (value === null || value === undefined) return "—";
  return Number(value).toLocaleString("en-US");
}

/** Tehran wall-clock, because that is the day the workbook groups by. Rendering a UTC
 *  timestamp would put late-evening Tehran stories on the previous day. */
export function tehranTime(iso) {
  if (!iso) return "—";
  return new Date(iso).toLocaleString("en-GB", {
    timeZone: "Asia/Tehran",
    day: "2-digit",
    month: "short",
    hour: "2-digit",
    minute: "2-digit",
  });
}
