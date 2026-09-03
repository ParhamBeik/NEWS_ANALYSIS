"use client";

import { useEffect, useState } from "react";
import { Card, SectionTitle } from "@/components/primitives";
import { AXIS_LABEL, CATEGORY_LABEL, LEVEL_ORDER, LEVEL_STYLE } from "@/lib/display";
import { skipCase, submitLabel } from "./actions";

const AXES = ["confidence_occurrence", "gold_price_impact", "security_relevance"];
const TRENDS = ["↑", "↓", "خنثی", "نامطمئن"];
const CATEGORIES = ["security", "economics", "security/economics", "other"];

/**
 * The labelling form, pre-filled with the model's own answer.
 *
 * Two things this gets right and a blank form would not:
 *
 * 1. Correcting is faster and more consistent than filling in, so a disagreement becomes a
 *    deliberate act rather than an omission.
 * 2. "Not assessed" is a real, clickable choice on every axis, visually distinct from the
 *    lowest level. If leaving a field blank were the only way to express it, blanks would
 *    accumulate from fatigue and be indistinguishable from a real judgement of "unknown" -
 *    and those blanks become the ground truth the model is scored against.
 */
function AxisRow({ axis, value, modelValue, onChange }) {
  return (
    <div className="border-t border-slate-800 py-2">
      <div className="mb-1.5 flex items-baseline justify-between">
        <span className="text-xs text-slate-400">{AXIS_LABEL[axis]}</span>
        {modelValue && (
          <span className="text-[11px] text-slate-600">
            model said <bdi className="persian text-slate-500">{modelValue}</bdi>
          </span>
        )}
      </div>
      <div className="flex flex-wrap gap-1.5">
        {LEVEL_ORDER.map((level) => (
          <button
            key={level}
            type="button"
            onClick={() => onChange(axis, level)}
            className={`persian rounded-md border px-2 py-1 text-xs transition ${
              value === level
                ? LEVEL_STYLE[level]
                : "border-slate-800 text-slate-500 hover:border-slate-600"
            }`}
          >
            <bdi>{level}</bdi>
          </button>
        ))}
        <button
          type="button"
          onClick={() => onChange(axis, null)}
          className={`rounded-md border px-2 py-1 text-xs transition ${
            value === null || value === undefined
              ? "border-dashed border-slate-600 text-slate-300"
              : "border-slate-800 text-slate-600 hover:border-slate-600"
          }`}
          title="This axis cannot be judged from this article. Stored as NULL, never as a level."
        >
          not assessed
        </button>
      </div>
    </div>
  );
}

export default function ReviewForm({ initialCase }) {
  const [reviewCase, setReviewCase] = useState(initialCase);
  const [form, setForm] = useState({});
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [done, setDone] = useState(0);

  // Reset to the new case's model answer whenever the case changes, NOT on every render:
  // carrying the previous article's scores into the next form is how a labelling session
  // silently produces a run of identical rows.
  useEffect(() => {
    if (!reviewCase) return;
    const answer = reviewCase.model_answer || {};
    setForm({
      reviewed_category: answer.category || "other",
      confidence_occurrence: answer.confidence_occurrence ?? null,
      gold_price_impact: answer.gold_price_impact ?? null,
      security_relevance: answer.security_relevance ?? null,
      gold_trend: answer.gold_trend ?? null,
      one_line: answer.one_line || "",
      reviewer_notes: "",
    });
  }, [reviewCase?.id]);

  async function run(action) {
    setBusy(true);
    setError("");
    try {
      const next = await action();
      setReviewCase(next);
      setDone((count) => count + 1);
    } catch (err) {
      setError(err.message);
    } finally {
      setBusy(false);
    }
  }

  if (!reviewCase) {
    return (
      <Card className="p-10 text-center">
        <p className="text-slate-300">The review queue is empty.</p>
        <p className="mt-2 text-sm text-slate-500">
          {done > 0
            ? `You labelled ${done} article${done === 1 ? "" : "s"} this session.`
            : "Run the sampler to queue articles: disagreements, `other` verdicts and a category round-robin."}
        </p>
      </Card>
    );
  }

  const article = reviewCase.article;
  const set = (key, value) => setForm((current) => ({ ...current, [key]: value }));

  return (
    <div className="grid gap-4 lg:grid-cols-2">
      <Card className="p-4">
        <div className="flex flex-wrap items-center gap-2 text-xs text-slate-500">
          <span className="rounded bg-slate-800 px-1.5 py-0.5 text-slate-300">
            {article.source}
          </span>
          <span className="tabular">{article.published_at_jalali}</span>
          <span className="rounded bg-slate-800/60 px-1.5 py-0.5">
            stratum: {reviewCase.stratum}
          </span>
          <a
            href={article.url}
            target="_blank"
            rel="noreferrer noopener"
            className="text-emerald-500 hover:underline"
          >
            original ↗
          </a>
        </div>
        <h2 dir="rtl" className="persian mt-2 text-lg font-semibold text-slate-100">
          {article.title}
        </h2>
        {article.lead && (
          <p dir="rtl" className="persian mt-2 text-sm text-slate-300">
            {article.lead}
          </p>
        )}
        {article.content && (
          <div
            dir="rtl"
            className="persian mt-3 max-h-96 overflow-y-auto whitespace-pre-wrap text-sm text-slate-400"
          >
            {article.content}
          </div>
        )}
      </Card>

      <Card className="p-4">
        <SectionTitle hint={`${done} labelled this session`}>Your label</SectionTitle>

        <div className="mb-2">
          <span className="text-xs text-slate-400">Category</span>
          <div className="mt-1.5 flex flex-wrap gap-1.5">
            {CATEGORIES.map((category) => (
              <button
                key={category}
                type="button"
                onClick={() => set("reviewed_category", category)}
                className={`rounded-md border px-2 py-1 text-xs transition ${
                  form.reviewed_category === category
                    ? "border-emerald-700 bg-emerald-950 text-emerald-300"
                    : "border-slate-800 text-slate-500 hover:border-slate-600"
                }`}
              >
                {CATEGORY_LABEL[category]}
              </button>
            ))}
          </div>
        </div>

        {AXES.map((axis) => (
          <AxisRow
            key={axis}
            axis={axis}
            value={form[axis]}
            modelValue={reviewCase.model_answer?.[axis]}
            onChange={set}
          />
        ))}

        <div className="border-t border-slate-800 py-2">
          <span className="text-xs text-slate-400">Gold trend</span>
          <div className="mt-1.5 flex flex-wrap gap-1.5">
            {TRENDS.map((trend) => (
              <button
                key={trend}
                type="button"
                onClick={() => set("gold_trend", form.gold_trend === trend ? null : trend)}
                className={`persian rounded-md border px-2.5 py-1 text-xs transition ${
                  form.gold_trend === trend
                    ? "border-emerald-700 bg-emerald-950 text-emerald-300"
                    : "border-slate-800 text-slate-500 hover:border-slate-600"
                }`}
              >
                <bdi>{trend}</bdi>
              </button>
            ))}
          </div>
        </div>

        <textarea
          value={form.one_line || ""}
          onChange={(event) => set("one_line", event.target.value)}
          dir="rtl"
          rows={2}
          placeholder="یک جمله برای کارتابل"
          className="persian mt-2 w-full rounded-lg border border-slate-800 bg-slate-950 px-3 py-2 text-sm outline-none focus:border-emerald-700"
        />
        <textarea
          value={form.reviewer_notes || ""}
          onChange={(event) => set("reviewer_notes", event.target.value)}
          dir="auto"
          rows={2}
          placeholder="Notes — why you disagreed with the model, if you did"
          className="mt-2 w-full rounded-lg border border-slate-800 bg-slate-950 px-3 py-2 text-sm outline-none focus:border-emerald-700"
        />

        {error && <p className="mt-2 text-xs text-rose-400">{error}</p>}

        <div className="mt-3 flex items-center gap-2">
          <button
            disabled={busy}
            onClick={() =>
              run(() =>
                submitLabel(reviewCase.id, {
                  ...form,
                  // null must survive as null. Sending "" would let DRF's CharField coerce
                  // it into a stored empty string, which is a sentinel by another name.
                  confidence_occurrence: form.confidence_occurrence,
                  gold_price_impact: form.gold_price_impact,
                  security_relevance: form.security_relevance,
                }),
              )
            }
            className="rounded-lg bg-emerald-500 px-3 py-1.5 text-sm font-medium text-slate-950 hover:bg-emerald-400 disabled:opacity-40"
          >
            {busy ? "Saving…" : "Approve label"}
          </button>
          <button
            disabled={busy}
            onClick={() => run(() => skipCase(reviewCase.id, form.reviewer_notes))}
            className="rounded-lg border border-slate-800 px-3 py-1.5 text-sm text-slate-400 hover:bg-slate-900 disabled:opacity-40"
          >
            Skip
          </button>
          <span className="text-xs text-slate-600">
            Skipping is data too — an article you cannot label is not one the model should
            be scored against.
          </span>
        </div>
      </Card>
    </div>
  );
}
