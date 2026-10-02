"use client";

import { useMemo, useState } from "react";

const KINDS = [
  ["asset", "Assets", "دارایی‌ها"],
  ["actor", "Actors", "بازیگران و نهادها"],
  ["theme", "Themes", "موضوع‌ها"],
];

export const DIALS = [
  ["low", "Low", "کم", "Tier 2 and above: more alerts", "اثر ۲ به بالا؛ هشدار بیشتر"],
  ["medium", "Medium", "متوسط", "Tier 3 and above", "اثر ۳ به بالا"],
  ["high", "High", "زیاد", "Tier 4 and above: only the big ones", "اثر ۴ به بالا؛ فقط خبرهای مهم"],
];

/** Watch-item chips as checkboxes named `slug`, grouped by kind, with a filter box. */
export function WatchPicker({ items, selected = [], lang }) {
  const fa = lang !== "en";
  const [chosen, setChosen] = useState(() => new Set(selected));
  const [filter, setFilter] = useState("");
  const groups = useMemo(() => {
    const needle = filter.trim().toLowerCase();
    return KINDS.map(([kind, en, faName]) => [kind, fa ? faName : en, items.filter((item) => item.kind === kind
      && (!needle || item.name_fa.includes(needle) || item.name_en.toLowerCase().includes(needle)))]);
  }, [items, filter, fa]);
  const toggle = (slug, on) => setChosen((current) => {
    const next = new Set(current);
    if (on) next.add(slug); else next.delete(slug);
    return next;
  });

  return <fieldset className="space-y-4">
    <legend className="sr-only">{fa ? "موارد پیگیری" : "Watch items"}</legend>
    <div className="flex flex-wrap items-center gap-3">
      <input type="search" value={filter} onChange={(event) => setFilter(event.target.value)}
        placeholder={fa ? "جست‌وجو: دلار، نفت، بانک مرکزی…" : "Search: dollar, oil, central bank…"}
        aria-label={fa ? "جست‌وجوی موارد" : "Filter items"}
        className="min-w-0 flex-1 rounded-xl border border-line bg-card px-4 py-2.5 text-sm outline-none focus:border-accent" />
      <span role="status" className="text-sm text-muted">{fa ? `${chosen.size.toLocaleString("fa-IR")} مورد انتخاب شده` : `${chosen.size} selected`}</span>
    </div>
    {/* Chosen items stay in the form even when the filter hides their chip. */}
    {[...chosen].filter((slug) => !groups.some(([, , rows]) => rows.some((item) => item.slug === slug)))
      .map((slug) => <input key={slug} type="hidden" name="slug" value={slug} />)}
    {groups.map(([kind, title, rows]) => rows.length ? <section key={kind} aria-label={title}>
      <h3 className="mb-2 text-sm font-semibold text-muted">{title}</h3>
      <div className="flex flex-wrap gap-2">
        {rows.map((item) => <label key={item.slug} className="cursor-pointer">
          <input type="checkbox" name="slug" value={item.slug} checked={chosen.has(item.slug)}
            onChange={(event) => toggle(item.slug, event.target.checked)} className="peer sr-only" />
          <span className="inline-flex items-center rounded-full border border-line bg-card px-3.5 py-1.5 text-sm transition peer-checked:border-accent-strong peer-checked:bg-accent-strong peer-checked:text-white peer-focus-visible:outline-2 peer-focus-visible:outline-accent hover:border-accent">
            {fa ? item.name_fa : item.name_en}
          </span>
        </label>)}
      </div>
    </section> : null)}
  </fieldset>;
}

/** The alert dial: which event tiers on the watchlist alert at all. */
export function DialPicker({ value = "medium", lang }) {
  const fa = lang !== "en";
  return <fieldset className="space-y-2">
    <legend className="mb-2 text-base font-bold">{fa ? "حساسیت هشدار" : "Alert dial"}</legend>
    <div className="grid gap-2 sm:grid-cols-3">
      {DIALS.map(([key, en, faName, hintEn, hintFa]) => <label key={key} className="cursor-pointer">
        <input type="radio" name="dial" value={key} defaultChecked={value === key} className="peer sr-only" />
        <span className="block rounded-xl border border-line bg-card p-3 transition peer-checked:border-accent-strong peer-checked:ring-2 peer-checked:ring-accent-strong peer-focus-visible:outline-2 peer-focus-visible:outline-accent">
          <span className="block font-semibold">{fa ? faName : en}</span>
          <span className="block text-xs text-muted">{fa ? hintFa : hintEn}</span>
        </span>
      </label>)}
    </div>
  </fieldset>;
}
