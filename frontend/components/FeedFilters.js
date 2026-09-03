"use client";

import { usePathname, useRouter, useSearchParams } from "next/navigation";

/**
 * Filters live in the URL, not in component state.
 *
 * That makes a filtered view shareable and bookmarkable, survives a refresh, and lets the
 * feed stay a server component - the alternative is fetching on the client and giving up
 * server rendering for the whole page to support a dropdown.
 */
export default function FeedFilters({ sources, categories, notifyStates, current }) {
  const router = useRouter();
  const pathname = usePathname();
  const params = useSearchParams();

  function update(key, value) {
    const next = new URLSearchParams(params);
    if (value) next.set(key, value);
    else next.delete(key);
    // Changing a filter must reset paging, or you land on page 4 of a 1-page result and
    // the feed looks empty.
    next.delete("offset");
    router.push(`${pathname}?${next.toString()}`);
  }

  const select =
    "rounded-lg border border-slate-800 bg-slate-900 px-2.5 py-1.5 text-sm text-slate-300 outline-none focus:border-emerald-700";

  return (
    <div className="mb-5 flex flex-wrap items-center gap-2">
      <input
        defaultValue={current.q || ""}
        placeholder="Search Persian text…"
        dir="auto"
        onKeyDown={(event) => {
          if (event.key === "Enter") update("q", event.currentTarget.value.trim());
        }}
        className={`${select} persian min-w-56`}
      />
      <select className={select} value={current.source || ""} onChange={(e) => update("source", e.target.value)}>
        <option value="">All sources</option>
        {sources.map((source) => (
          <option key={source.name} value={source.name}>
            {source.display_name || source.name}
          </option>
        ))}
      </select>
      <select className={select} value={current.category || ""} onChange={(e) => update("category", e.target.value)}>
        <option value="">All categories</option>
        {categories.map(([value, label]) => (
          <option key={value} value={value}>
            {label}
          </option>
        ))}
      </select>
      <select className={select} value={current.notify || ""} onChange={(e) => update("notify", e.target.value)}>
        <option value="">Any verdict</option>
        {notifyStates.map(([value, label]) => (
          <option key={value} value={value}>
            {label}
          </option>
        ))}
      </select>
      <label className="flex items-center gap-2 text-xs text-slate-500">
        <input
          type="checkbox"
          checked={current.unanalysed === "true"}
          onChange={(e) => update("unanalysed", e.target.checked ? "true" : "")}
          className="accent-emerald-500"
        />
        Unanalysed only
      </label>
      <label className="flex items-center gap-2 text-xs text-slate-500">
        <input
          type="checkbox"
          checked={current.include_duplicates === "true"}
          onChange={(e) => update("include_duplicates", e.target.checked ? "true" : "")}
          className="accent-emerald-500"
        />
        Show duplicates
      </label>
    </div>
  );
}
