import AsyncPanel, { Skeleton } from "@/components/AsyncPanel";
import { Card, SectionTitle } from "@/components/primitives";
import { apiGet } from "@/lib/api";
import { percent } from "@/lib/display";
import ABLab from "./ABLab";

export const metadata = { title: "A/B lab · News Intelligence" };
export const dynamic = "force-dynamic";

async function Judging() {
  const pair = await apiGet("/api/ab/pairs/next/");
  return <ABLab initialPair={pair} />;
}

/**
 * The standings and the bias check, in their own boundary.
 *
 * `/api/ab/pairs/results/` walks every judgement ever recorded to build the tally, while
 * the judging pane needs one row. Coupling them meant the aggregate's latency gated the
 * task, and its failure removed the ability to judge at all - for a sidebar.
 */
async function Standings() {
  const results = await apiGet("/api/ab/pairs/results/");
  const bias = results.position_bias.left_share_of_decided;
  // 0.5 is unbiased. Flagging past 0.65 rather than at any deviation: with a handful of
  // judgements a run of three lefts is noise, and a warning that cries wolf gets ignored
  // exactly when it starts being true.
  const biased = bias !== null && Math.abs(bias - 0.5) > 0.15 && results.judgements >= 10;

  return (
    <>
      <Card className="p-4">
        <SectionTitle hint={`${results.judgements} judged`}>Standings</SectionTitle>
        {results.standings.length === 0 ? (
          <p className="text-sm text-slate-500">
            No judgements yet. Standings appear once you have judged a pair.
          </p>
        ) : (
          <table className="w-full text-sm">
            <thead>
              <tr className="text-left text-[11px] uppercase tracking-wider text-slate-600">
                <th className="pb-1">Variant</th>
                <th className="pb-1 text-right">Win rate</th>
                <th className="pb-1 text-right">n</th>
              </tr>
            </thead>
            <tbody>
              {results.standings.map((row) => (
                <tr key={row.variant} className="border-t border-slate-800">
                  <td className="py-1.5">
                    <div className="text-slate-200">{row.variant}</div>
                    <div className="text-[11px] text-slate-600">
                      {row.model} · {row.memory_strategy}
                    </div>
                  </td>
                  <td className="py-1.5 text-right tabular text-emerald-400">
                    {percent(row.win_rate)}
                  </td>
                  <td className="py-1.5 text-right tabular text-slate-500">
                    {row.appearances}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </Card>

      {/* Reporting wins without this number would be dishonest: a reviewer who picks the
          left card regardless of content produces standings that measure the layout. */}
      <Card className={`p-4 ${biased ? "border-amber-900/60 bg-amber-950/20" : ""}`}>
        <SectionTitle>Position bias</SectionTitle>
        <p className="text-sm text-slate-400">
          Left chosen <span className="tabular text-slate-100">{percent(bias)}</span> of
          decided judgements ({results.position_bias.left_wins}L /{" "}
          {results.position_bias.right_wins}R / {results.position_bias.ties}T).
        </p>
        <p className="mt-2 text-xs text-slate-500">
          {biased
            ? "Well off 50%. The standings may be measuring which side of the screen you look at first, not which answer is better."
            : "50% is unbiased. Sides are randomised per pair with a CSPRNG, so a drift here is a real reading habit rather than a predictable sequence."}
        </p>
      </Card>
    </>
  );
}

export default async function ABPage() {
  return (
    <div className="grid gap-6 lg:grid-cols-[1fr_320px]">
      <div>
        <h1 className="mb-1 text-2xl font-semibold text-slate-100">A/B lab</h1>
        <p className="mb-5 text-sm text-slate-500">
          Two prompt variants answered the same article. You cannot see which is which —
          that is the point. Pick the better answer and say why.
        </p>
        <AsyncPanel label="The next pair" fallback={<Skeleton className="h-96 w-full" />}>
          <Judging />
        </AsyncPanel>
      </div>

      <aside className="space-y-4">
        <AsyncPanel label="Standings" fallback={<Skeleton className="h-56 w-full" />}>
          <Standings />
        </AsyncPanel>

        <Card className="p-4 text-xs text-slate-500">
          <SectionTitle>How pairs are made</SectionTitle>
          Activate a second variant with <code className="text-slate-400">seed_variants</code>{" "}
          so both arms answer every article. An hourly task then pairs any article both arms
          have evaluated. Each active arm roughly doubles cost per cycle, which is why only
          the control ships active.
        </Card>
      </aside>
    </div>
  );
}
