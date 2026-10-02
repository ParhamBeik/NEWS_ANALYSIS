"use client";

import { useEffect, useRef, useState } from "react";
import { EVENT_CATEGORY, LEVEL_ORDER, LEVEL_STYLE, jalaliTime } from "@/lib/display";
import { gestureAction, keyAction } from "@/lib/swipe";
import { decide, sessionStats, splitArticle } from "./actions";

const TIER_EN = ["Very low", "Low", "Medium", "High", "Very high"];
const REASON = {
  high_impact_uncertain: ["High impact, low confidence", "اثر زیاد، اطمینان کم"],
  audit_sample: ["Random audit", "نمونهٔ تصادفی"],
};
const ANNOUNCE = {
  agree: ["Agreed", "تأیید شد"],
  fix: ["Correction saved", "اصلاح ثبت شد"],
  skip: ["Skipped", "رد شد"],
  undo: ["Undone", "بازگردانده شد"],
  split: ["Article moved to its own event", "خبر به رویداد جدا منتقل شد"],
};

/**
 * Swipe review of Jev's event judgments, built for one thumb on a phone.
 *
 * Right (swipe, → or "Agree") confirms the model's tiers and category; left (swipe, ← or
 * "Fix") opens one-tap pickers pre-filled with the model's answer; ↓ skips; Ctrl/Cmd+Z
 * undoes. Every save is awaited before the next card shows, so the progress count is
 * always what the server holds.
 */
export default function SwipeReview({ initialCards, pending, lang }) {
  const fa = lang === "fa";
  const t = (en, persian) => (fa ? persian : en);
  const [cards, setCards] = useState(initialCards);
  const [index, setIndex] = useState(0);
  const [mode, setMode] = useState("card");
  const [draft, setDraft] = useState(null);
  const [history, setHistory] = useState([]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [announcement, setAnnouncement] = useState("");
  const [stats, setStats] = useState(null);
  const [dx, setDx] = useState(0);
  const drag = useRef(null);
  const sessionStart = useRef(new Date().toISOString());
  const panel = useRef(null);
  const handlers = useRef({});

  const card = cards[index];
  const done = index >= cards.length;

  async function run(work, message, after) {
    if (busy) return;
    setBusy(true);
    setError("");
    try {
      const result = await work();
      after(result);
      setAnnouncement(t(...ANNOUNCE[message]));
    } catch {
      setError(t("Could not save. Check the connection and try again.", "ذخیره نشد. اتصال را بررسی و دوباره تلاش کنید."));
    } finally {
      setBusy(false);
    }
  }

  function act(action, extra = {}) {
    if (!card) return;
    const position = index;
    const eventId = card.id;
    run(() => decide(eventId, { action, ...extra }), action, () => {
      setHistory((rows) => [...rows, { index: position, eventId }]);
      setIndex(position + 1);
      setMode("card");
    });
  }

  function undo() {
    const last = history.at(-1);
    if (!last) return;
    run(() => decide(last.eventId, { action: "undo" }), "undo", () => {
      setHistory((rows) => rows.slice(0, -1));
      setIndex(last.index);
      setStats(null);
      setMode("card");
    });
  }

  function openFix() {
    if (!card) return;
    setDraft({ category: card.category, iran_tier: card.iran_level, global_tier: card.global_level });
    setMode("fix");
  }

  function split(articleId) {
    const position = index;
    run(() => splitArticle(card.id, articleId), "split", (result) => {
      if (result?.card) setCards((rows) => rows.map((row, i) => (i === position ? result.card : row)));
      setMode("card");
    });
  }

  handlers.current = { act, undo, openFix, mode, done };

  useEffect(() => {
    function onKey(event) {
      if (event.target.closest?.("input, textarea, select")) return;
      const { act: doAct, undo: doUndo, openFix: doFix, mode: current, done: finished } = handlers.current;
      const action = keyAction(event);
      if (action === "undo") {
        event.preventDefault();
        doUndo();
      } else if (event.key === "Escape" && current !== "card") {
        setMode("card");
      } else if (action && current === "card" && !finished) {
        event.preventDefault();
        if (action === "fix") doFix();
        else doAct(action);
      }
    }
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);

  useEffect(() => {
    if (mode !== "card") panel.current?.focus();
  }, [mode]);

  useEffect(() => {
    if (!done || stats) return;
    sessionStats(sessionStart.current).then(setStats).catch(() => setStats({ failed: true }));
  }, [done, stats]);

  if (!initialCards.length) {
    return (
      <div className="mx-auto max-w-md py-16 text-center">
        <h1 className="text-xl font-semibold text-slate-100">{t("Nothing to review", "موردی برای بازبینی نیست")}</h1>
        <p className="mt-2 text-sm text-slate-300">
          {t("The model has no pending judgments waiting for a human check.", "داوری در انتظار بازبینی وجود ندارد.")}
        </p>
      </div>
    );
  }

  const total = cards.length;
  const position = Math.min(index + 1, total);
  const tier = (value) => (value == null ? t("Not assessed", "ارزیابی نشده") : fa ? LEVEL_ORDER[value] : TIER_EN[value]);
  const categoryName = (key) => (EVENT_CATEGORY[key] ? EVENT_CATEGORY[key][fa ? 1 : 0] : key);

  function onPointerDown(event) {
    if (mode !== "card" || busy || event.target.closest("button, a")) return;
    drag.current = { x: event.clientX, y: event.clientY };
    event.currentTarget.setPointerCapture(event.pointerId);
  }
  function onPointerMove(event) {
    if (drag.current) setDx(event.clientX - drag.current.x);
  }
  function onPointerUp(event) {
    const start = drag.current;
    drag.current = null;
    setDx(0);
    if (!start) return;
    const action = gestureAction(event.clientX - start.x, event.clientY - start.y);
    if (action === "agree") act("agree");
    else if (action === "fix") openFix();
  }

  return (
    <div className="mx-auto max-w-md pb-48">
      <div className="mb-3 flex items-center gap-3">
        <h1 className="text-base font-semibold text-slate-100">{t("Quick review", "بازبینی سریع")}</h1>
        <span className="ms-auto text-sm tabular text-slate-300">
          {done ? t("Done", "پایان") : `${position.toLocaleString(fa ? "fa-IR" : "en-US")} / ${total.toLocaleString(fa ? "fa-IR" : "en-US")}`}
        </span>
      </div>
      <div
        role="progressbar"
        aria-label={t("Session progress", "پیشرفت جلسه")}
        aria-valuemin={0}
        aria-valuemax={total}
        aria-valuenow={Math.min(index, total)}
        className="mb-4 h-2 overflow-hidden rounded-full bg-slate-800"
      >
        <div className="h-full bg-emerald-400 motion-safe:transition-all" style={{ width: `${(Math.min(index, total) / total) * 100}%` }} />
      </div>
      <p aria-live="polite" className="sr-only">{announcement}</p>
      {error ? <p role="alert" className="mb-3 rounded-lg border border-amber-700 bg-amber-950 p-3 text-sm text-amber-100">{error}</p> : null}

      {done ? (
        <Summary stats={stats} t={t} fa={fa} categoryName={categoryName} more={pending > total} />
      ) : (
        <article
          aria-roledescription={t("review card", "کارت بازبینی")}
          aria-label={card.title}
          onPointerDown={onPointerDown}
          onPointerMove={onPointerMove}
          onPointerUp={onPointerUp}
          onPointerCancel={() => { drag.current = null; setDx(0); }}
          style={{ transform: dx ? `translateX(${dx}px) rotate(${dx / 40}deg)` : undefined, touchAction: "pan-y" }}
          className={`select-none overflow-hidden rounded-2xl border bg-slate-900 ${
            dx > 40 ? "border-emerald-400" : dx < -40 ? "border-amber-400" : "border-slate-700"
          } ${dx ? "" : "motion-safe:transition-transform"} ${busy ? "opacity-60" : ""}`}
        >
          {card.image_url ? <img src={card.image_url} alt="" draggable={false} className="aspect-video max-h-48 w-full object-cover" /> : null}
          <div className="p-4">
            <div className="flex flex-wrap items-center gap-x-2 gap-y-1 text-xs text-slate-300">
              <span className="rounded bg-slate-800 px-2 py-0.5">{REASON[card.review_reason]?.[fa ? 1 : 0] ?? card.review_reason}</span>
              {card.skipped ? <span className="rounded bg-slate-800 px-2 py-0.5">{t("Skipped before", "قبلاً رد شده")}</span> : null}
              <span>{card.sources[0]?.name}{card.sources.length > 1 ? ` +${(card.sources.length - 1).toLocaleString(fa ? "fa-IR" : "en-US")}` : ""}</span>
              <span aria-hidden="true">·</span>
              <time dateTime={card.event_time} suppressHydrationWarning>{jalaliTime(card.event_time, lang)}</time>
            </div>
            <h2 dir="auto" className="persian mt-2 text-lg font-semibold leading-8 text-slate-100">
              {(fa ? card.title_fa : card.title_en) || card.original_title}
            </h2>
            {(fa ? card.title_fa : card.title_en) && card.original_title !== (fa ? card.title_fa : card.title_en) ? (
              <p dir="auto" className="persian mt-1 text-sm text-slate-300">{card.original_title}</p>
            ) : null}

            <div className="mt-4 grid grid-cols-2 gap-2">
              <Judgment label={t("Impact on Iran", "اثر بر ایران")} value={tier(card.iran_level)} tierValue={card.iran_level} big />
              <Judgment label={t("Global impact", "اثر جهانی")} value={tier(card.global_level)} tierValue={card.global_level} big />
            </div>
            <div className="mt-2 rounded-xl border border-slate-700 bg-slate-950 p-3">
              <p className="text-xs text-slate-300">{t("Category", "دسته")}</p>
              <p className="text-xl font-semibold text-slate-100">{categoryName(card.category)}</p>
            </div>
            {card.assessment_confidence != null ? (
              <p className="mt-2 text-xs text-slate-300">
                {t("Model confidence", "اطمینان مدل")}: <bdi className="tabular">{percent(card.assessment_confidence, fa)}</bdi>
              </p>
            ) : null}
          </div>
        </article>
      )}

      {!done && mode === "fix" ? (
        <section ref={panel} tabIndex={-1} aria-label={t("Correct the judgment", "اصلاح داوری")} className="mt-4 space-y-4 rounded-2xl border border-amber-700 bg-slate-900 p-4 outline-none">
          <Picker legend={t("Impact on Iran", "اثر بر ایران")} options={LEVEL_ORDER.map((_, i) => [i, tier(i)])} value={draft.iran_tier} onPick={(v) => setDraft({ ...draft, iran_tier: v })} />
          <Picker legend={t("Global impact", "اثر جهانی")} options={LEVEL_ORDER.map((_, i) => [i, tier(i)])} value={draft.global_tier} onPick={(v) => setDraft({ ...draft, global_tier: v })} />
          <Picker legend={t("Category", "دسته")} columns options={Object.keys(EVENT_CATEGORY).map((key) => [key, categoryName(key)])} value={draft.category} onPick={(v) => setDraft({ ...draft, category: v })} />
        </section>
      ) : null}

      {!done && mode === "split" ? (
        <section ref={panel} tabIndex={-1} aria-label={t("Not the same event", "رویداد یکسان نیست")} className="mt-4 rounded-2xl border border-slate-700 bg-slate-900 p-4 outline-none">
          <p className="mb-3 text-sm text-slate-200">{t("Which report is a different event? It moves to its own event and is assessed again.", "کدام خبر رویداد دیگری است؟ به رویداد جدا منتقل و دوباره ارزیابی می‌شود.")}</p>
          <ul className="space-y-2">
            {card.articles.map((article) => (
              <li key={article.id} className="flex items-center gap-2 rounded-lg bg-slate-950 p-2">
                <div className="min-w-0 flex-1">
                  <p dir="auto" className="persian text-sm text-slate-100">{article.title}</p>
                  <p className="text-xs text-slate-300">{article.source}</p>
                </div>
                <button type="button" disabled={busy} onClick={() => split(article.id)} className="min-h-11 shrink-0 rounded-lg border border-slate-600 px-3 text-sm text-slate-100 hover:bg-slate-800 disabled:opacity-50">
                  {t("Split out", "جدا کن")}
                </button>
              </li>
            ))}
          </ul>
        </section>
      ) : null}

      <div className="fixed inset-x-0 bottom-0 z-30 border-t border-slate-800 bg-slate-950/95 px-3 pt-2 backdrop-blur" style={{ paddingBottom: "max(0.75rem, env(safe-area-inset-bottom))" }}>
        <div className="mx-auto max-w-md">
          <div className="mb-2 flex gap-2">
            <button type="button" onClick={undo} disabled={busy || !history.length} aria-keyshortcuts="Control+Z Meta+Z" className="min-h-11 rounded-lg border border-slate-700 px-3 text-sm text-slate-200 disabled:opacity-40">
              ↶ {t("Undo", "واگرد")}
            </button>
            {!done && card.articles.length > 1 ? (
              <button type="button" onClick={() => setMode(mode === "split" ? "card" : "split")} aria-expanded={mode === "split"} className="ms-auto min-h-11 rounded-lg border border-slate-700 px-3 text-sm text-slate-200">
                {t("Not the same event", "رویداد یکسان نیست")}
              </button>
            ) : null}
          </div>
          {done ? null : mode === "fix" ? (
            <div dir="ltr" className="grid grid-cols-2 gap-2">
              <button type="button" onClick={() => setMode("card")} className="min-h-14 rounded-xl border border-slate-600 text-base text-slate-100">
                {t("Cancel", "انصراف")}
              </button>
              <button type="button" disabled={busy} onClick={() => act("fix", draft)} className="min-h-14 rounded-xl bg-amber-400 text-base font-semibold text-slate-950 disabled:opacity-50">
                {t("Save fix", "ثبت اصلاح")}
              </button>
            </div>
          ) : (
            // Physical order on purpose: Fix sits under the left swipe, Agree under the right.
            <div dir="ltr" className="grid grid-cols-[1fr_auto_1fr] gap-2">
              <button type="button" disabled={busy} onClick={openFix} aria-keyshortcuts="ArrowLeft" className="min-h-14 rounded-xl border border-amber-400 text-base font-semibold text-amber-200 disabled:opacity-50">
                ← {t("Fix", "اصلاح")}
              </button>
              <button type="button" disabled={busy} onClick={() => act("skip")} aria-keyshortcuts="ArrowDown" className="min-h-14 rounded-xl border border-slate-600 px-4 text-sm text-slate-200 disabled:opacity-50">
                ↓ {t("Skip", "رد")}
              </button>
              <button type="button" disabled={busy} onClick={() => act("agree")} aria-keyshortcuts="ArrowRight" className="min-h-14 rounded-xl bg-emerald-400 text-base font-semibold text-slate-950 disabled:opacity-50">
                {t("Agree", "موافقم")} →
              </button>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}

function Judgment({ label, value, tierValue, big }) {
  const style = tierValue == null ? "border-dashed border-slate-600 text-slate-300" : LEVEL_STYLE[LEVEL_ORDER[tierValue]];
  return (
    <div className={`rounded-xl border p-3 ${style}`}>
      <p className="text-xs opacity-90">{label}</p>
      <p className={`persian font-bold ${big ? "text-2xl" : "text-lg"}`}>{value}</p>
    </div>
  );
}

function Picker({ legend, options, value, onPick, columns = false }) {
  return (
    <fieldset>
      <legend className="mb-2 text-sm font-medium text-slate-200">{legend}</legend>
      <div className={`grid gap-2 ${columns ? "grid-cols-2" : "grid-cols-5"}`}>
        {options.map(([key, text]) => (
          <button
            key={key}
            type="button"
            aria-pressed={value === key}
            onClick={() => onPick(key)}
            className={`persian min-h-11 rounded-lg border px-1 text-sm leading-tight ${
              value === key ? "border-emerald-300 bg-emerald-400 font-semibold text-slate-950" : "border-slate-600 text-slate-100 hover:bg-slate-800"
            }`}
          >
            {text}
          </button>
        ))}
      </div>
    </fieldset>
  );
}

function percent(value, fa) {
  return value == null ? "—" : new Intl.NumberFormat(fa ? "fa-IR" : "en-US", { style: "percent" }).format(value);
}

function Summary({ stats, t, fa, categoryName, more }) {
  const pct = (value) => percent(value, fa);
  const num = (value) => Number(value).toLocaleString(fa ? "fa-IR" : "en-US");
  if (!stats) return <p className="text-sm text-slate-300">{t("Loading summary…", "در حال بارگذاری خلاصه…")}</p>;
  if (stats.failed) return <p role="alert" className="text-sm text-amber-200">{t("Summary unavailable.", "خلاصه در دسترس نیست.")}</p>;
  return (
    <section className="rounded-2xl border border-slate-700 bg-slate-900 p-4">
      <h2 className="text-lg font-semibold text-slate-100">{t("Session summary", "خلاصهٔ جلسه")}</h2>
      <dl className="mt-3 grid grid-cols-2 gap-2">
        <div className="rounded-xl bg-slate-950 p-3">
          <dt className="text-xs text-slate-300">{t("Reviewed", "بازبینی‌شده")}</dt>
          <dd className="text-2xl font-bold tabular text-slate-100">{num(stats.reviewed)}</dd>
        </div>
        <div className="rounded-xl bg-slate-950 p-3">
          <dt className="text-xs text-slate-300">{t("Agreed with model", "توافق با مدل")}</dt>
          <dd className="text-2xl font-bold tabular text-slate-100">{pct(stats.agreement_rate)}</dd>
        </div>
      </dl>
      {stats.categories.length ? (
        <table className="mt-4 w-full text-sm">
          <caption className="sr-only">{t("Agreement by model category", "توافق به تفکیک دسته")}</caption>
          <thead>
            <tr className="text-xs text-slate-300">
              <th scope="col" className="py-1 text-start font-medium">{t("Category", "دسته")}</th>
              <th scope="col" className="py-1 text-end font-medium">{t("Cards", "تعداد")}</th>
              <th scope="col" className="py-1 text-end font-medium">{t("Agreement", "توافق")}</th>
            </tr>
          </thead>
          <tbody>
            {stats.categories.map((row) => (
              <tr key={row.category} className="border-t border-slate-800 text-slate-100">
                <th scope="row" className="py-2 text-start font-normal">{categoryName(row.category)}</th>
                <td className="py-2 text-end tabular">{num(row.reviewed)}</td>
                <td className="py-2 text-end tabular">{pct(row.agreement_rate)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      ) : null}
      <a href="/review/swipe" className="mt-4 flex min-h-12 items-center justify-center rounded-xl bg-emerald-400 font-semibold text-slate-950">
        {more ? t("Next session", "جلسهٔ بعد") : t("Check for new cards", "بررسی موارد تازه")}
      </a>
    </section>
  );
}
