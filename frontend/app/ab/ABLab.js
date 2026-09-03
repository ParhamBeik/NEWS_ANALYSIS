"use client";

import { useCallback, useEffect, useState } from "react";
import { Card, CategoryBadge, ScoreChip, SectionTitle } from "@/components/primitives";
import { submitJudgement } from "./actions";

const AXES = ["confidence_occurrence", "gold_price_impact", "security_relevance"];

/**
 * The blinded head-to-head.
 *
 * Nothing on this screen names a model, and nothing in the payload could: the API sends
 * "left" and "right" and keeps the mapping server-side. The reveal appears only after the
 * judgement is stored - seeing it a moment earlier would bias the judgement it is
 * reporting on.
 *
 * Keyboard-driven (1 / 2 / 3) because this is a repetitive task and a mouse round trip per
 * item is what makes a labelling session stop after fifteen items instead of a hundred.
 */
function Side({ label, data, hotkey, onPick, disabled }) {
  return (
    <Card className="flex flex-col p-4">
      <div className="mb-3 flex items-center justify-between">
        <h3 className="text-sm font-semibold uppercase tracking-widest text-slate-400">
          {label}
        </h3>
        <kbd className="rounded border border-slate-700 bg-slate-800 px-1.5 text-[11px] text-slate-400">
          {hotkey}
        </kbd>
      </div>

      <div className="mb-3 flex items-center gap-2">
        <CategoryBadge category={data.category} />
        {data.confidence?.value && (
          <span className="text-xs text-slate-500">
            confidence <bdi className="persian">{data.confidence.value}</bdi>
          </span>
        )}
        {data.gold_trend?.value && (
          <bdi className="persian text-sm text-slate-300">{data.gold_trend.value}</bdi>
        )}
      </div>

      {data.scores && (
        <div className="space-y-1.5">
          {AXES.map((axis) => (
            <ScoreChip key={axis} axis={axis} score={data.scores[axis]} />
          ))}
        </div>
      )}

      {data.decision && (
        <p className="mt-2 text-xs text-slate-500">{data.decision.reason}</p>
      )}

      {data.one_line && (
        <p dir="rtl" className="persian mt-3 rounded-lg bg-slate-950/60 p-2 text-sm text-slate-200">
          {data.one_line}
        </p>
      )}

      {data.evaluation_rationale && (
        <p dir="rtl" className="persian mt-2 text-xs text-slate-400">
          {data.evaluation_rationale}
        </p>
      )}

      <button
        onClick={() => onPick(label.toLowerCase())}
        disabled={disabled}
        className="mt-auto pt-4 text-sm text-emerald-400 transition hover:text-emerald-300 disabled:opacity-40"
      >
        Pick {label.toLowerCase()} →
      </button>
    </Card>
  );
}

export default function ABLab({ initialPair, initialStandings }) {
  const [pair, setPair] = useState(initialPair);
  const [reasoning, setReasoning] = useState("");
  const [revealed, setRevealed] = useState(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  const judge = useCallback(
    async (winner) => {
      if (!pair || busy) return;
      setBusy(true);
      setError("");
      try {
        const result = await submitJudgement(pair.id, winner, reasoning);
        setRevealed(result.revealed.revealed);
        setPair(result.next);
        setReasoning("");
      } catch (err) {
        setError(err.message);
      } finally {
        setBusy(false);
      }
    },
    [pair, reasoning, busy],
  );

  useEffect(() => {
    function onKey(event) {
      // Not while typing the "why": otherwise pressing 1 mid-sentence submits the form.
      if (event.target.tagName === "TEXTAREA" || event.target.tagName === "INPUT") return;
      if (event.key === "1") judge("left");
      if (event.key === "2") judge("right");
      if (event.key === "3") judge("tie");
    }
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [judge]);

  if (!pair) {
    return (
      <Card className="p-10 text-center">
        <p className="text-slate-300">No pairs left to judge.</p>
        <p className="mt-2 text-sm text-slate-500">
          Activate a second prompt variant so both arms answer the same articles, then run a
          cycle. Pairs are generated from articles that have an answer from two variants.
        </p>
        {revealed && (
          <p className="mt-4 text-xs text-slate-500">
            Last reveal — left: {revealed.left}, right: {revealed.right}, you chose{" "}
            <span className="text-emerald-400">{revealed.chosen || "tie"}</span>
          </p>
        )}
      </Card>
    );
  }

  return (
    <div className="space-y-4">
      <Card className="p-4">
        <div className="flex flex-wrap items-center gap-2 text-xs text-slate-500">
          <span className="rounded bg-slate-800 px-1.5 py-0.5 text-slate-300">
            {pair.article.source}
          </span>
          <span className="tabular">{pair.article.published_at_jalali}</span>
          <a
            href={pair.article.url}
            target="_blank"
            rel="noreferrer noopener"
            className="text-emerald-500 hover:underline"
          >
            original ↗
          </a>
        </div>
        <h2 dir="rtl" className="persian mt-2 text-lg font-semibold text-slate-100">
          {pair.article.title}
        </h2>
        {pair.article.lead && (
          <p dir="rtl" className="persian mt-1 text-sm text-slate-400">
            {pair.article.lead}
          </p>
        )}
      </Card>

      <div className="grid gap-4 md:grid-cols-2">
        <Side label="Left" hotkey="1" data={pair.left} onPick={judge} disabled={busy} />
        <Side label="Right" hotkey="2" data={pair.right} onPick={judge} disabled={busy} />
      </div>

      <Card className="p-4">
        <SectionTitle hint="optional, but this is the part that explains the score later">
          Why?
        </SectionTitle>
        <textarea
          value={reasoning}
          onChange={(event) => setReasoning(event.target.value)}
          rows={2}
          dir="auto"
          placeholder="What made the winner better? Wrong axis, missed the security angle, better one-liner…"
          className="w-full rounded-lg border border-slate-800 bg-slate-950 px-3 py-2 text-sm outline-none focus:border-emerald-700"
        />
        <div className="mt-3 flex items-center gap-2">
          <button
            onClick={() => judge("left")}
            disabled={busy}
            className="rounded-lg bg-slate-800 px-3 py-1.5 text-sm text-slate-200 hover:bg-slate-700 disabled:opacity-40"
          >
            Left wins <kbd className="text-slate-500">1</kbd>
          </button>
          <button
            onClick={() => judge("right")}
            disabled={busy}
            className="rounded-lg bg-slate-800 px-3 py-1.5 text-sm text-slate-200 hover:bg-slate-700 disabled:opacity-40"
          >
            Right wins <kbd className="text-slate-500">2</kbd>
          </button>
          <button
            onClick={() => judge("tie")}
            disabled={busy}
            className="rounded-lg border border-slate-800 px-3 py-1.5 text-sm text-slate-400 hover:bg-slate-900 disabled:opacity-40"
          >
            Tie <kbd className="text-slate-600">3</kbd>
          </button>
          {busy && <span className="text-xs text-slate-500">saving…</span>}
        </div>
        {error && <p className="mt-2 text-xs text-rose-400">{error}</p>}
      </Card>

      {revealed && (
        <Card className="border-emerald-900/50 bg-emerald-950/20 p-3 text-xs text-slate-400">
          Previous pair — left was <strong className="text-slate-200">{revealed.left}</strong>,
          right was <strong className="text-slate-200">{revealed.right}</strong>. You chose{" "}
          <strong className="text-emerald-400">{revealed.chosen || "tie"}</strong>.
        </Card>
      )}
    </div>
  );
}
