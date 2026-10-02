"use client";

import { useRouter } from "next/navigation";
import { useState, useTransition } from "react";
import { setArticleHidden, setEventHidden } from "./actions";

/** Staff-only takedown panel: hide or unhide the event or one report, with a reason. */
export default function TakedownControl({ state }) {
  const router = useRouter();
  const [reason, setReason] = useState("");
  const [error, setError] = useState("");
  const [busy, startTransition] = useTransition();

  function run(action) {
    if (!reason.trim()) { setError("A reason is required."); return; }
    setError("");
    startTransition(async () => {
      try { await action(reason.trim()); setReason(""); router.refresh(); }
      catch { setError("Not saved. Try again."); }
    });
  }

  const { event, articles, log } = state;
  return <details className="rounded-2xl border border-dashed border-line p-4 text-sm" open={event.hidden}>
    <summary className="cursor-pointer font-semibold">Staff: takedown {event.hidden ? "(event hidden)" : ""}</summary>
    <div className="mt-3 space-y-3" dir="ltr">
      <label className="block">
        <span className="text-xs text-muted">Reason (logged)</span>
        <input value={reason} onChange={(e) => setReason(e.target.value)} maxLength={255}
          className="mt-1 w-full rounded-lg border border-line bg-card-2 px-3 py-2" />
      </label>
      {error ? <p role="alert" className="text-xs">{error}</p> : null}
      <button type="button" disabled={busy} onClick={() => run((why) => setEventHidden(event.id, !event.hidden, why))}
        className="min-h-11 rounded-lg border border-line px-3 font-semibold disabled:opacity-50">
        {event.hidden ? "Unhide event" : "Hide event"}
      </button>
      <ul className="divide-y divide-line">{articles.map((article) => <li key={article.id} className="flex items-center justify-between gap-3 py-2">
        <span className="min-w-0 truncate" dir="auto">{article.hidden ? "[hidden] " : ""}{article.source}: {article.title}</span>
        <button type="button" disabled={busy} onClick={() => run((why) => setArticleHidden(article.id, !article.hidden, why))}
          className="min-h-11 shrink-0 rounded-lg border border-line px-3 disabled:opacity-50">{article.hidden ? "Unhide" : "Hide"}</button>
      </li>)}</ul>
      {log.length ? <ol className="space-y-1 text-xs text-muted">{log.map((row, index) => <li key={index}>
        {row.at} · {row.by || "system"} · {row.action} {row.kind} {row.id} · {row.reason}
      </li>)}</ol> : null}
    </div>
  </details>;
}
