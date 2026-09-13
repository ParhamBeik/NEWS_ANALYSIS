import AsyncPanel, { Skeleton } from "@/components/AsyncPanel";
import { Card, SectionTitle, TableScroll } from "@/components/primitives";
import { apiGet, currentStaffUser } from "@/lib/api";
import { percent } from "@/lib/display";
import ABLab from "./ABLab";

export const metadata = { title: "A/B lab · News Intelligence" };
export const dynamic = "force-dynamic";

async function Judging() {
  const pair = await apiGet("/api/ab/pairs/next/");
  return <ABLab initialPair={pair} />;
}

async function VariantSetup() {
  const data = await apiGet("/api/variants/?limit=20");
  const variants = data.results ?? data;
  const active = variants.filter((row) => row.is_active);
  const inactive = variants.filter((row) => !row.is_active);
  const ready = active.length >= 2;

  return (
    <Card className="p-4">
      <SectionTitle hint={`${active.length} active · costs ~${active.length}× per cycle`}>
        Prompt variants
      </SectionTitle>
      {variants.length === 0 ? (
        <p className="text-sm text-slate-500">
          No variants seeded yet. Run{" "}
          <code className="text-slate-400">python manage.py seed_variants</code> on the
          backend (creates control + inactive challengers; no API spend).
        </p>
      ) : (
        <>
          <ul className="space-y-2 text-sm">
            {variants.map((variant) => (
              <li
                key={variant.id}
                className="flex items-start justify-between gap-2 border-t border-slate-800 pt-2 first:border-0 first:pt-0"
              >
                <div className="min-w-0">
                  <span className="text-slate-200">{variant.name}</span>
                  <span className="text-slate-600"> · {variant.memory_strategy}</span>
                  {variant.description && (
                    <p className="mt-0.5 text-[11px] leading-snug text-slate-600">
                      {variant.description}
                    </p>
                  )}
                </div>
                <span
                  className={`shrink-0 text-xs ${
                    variant.is_active ? "text-emerald-400" : "text-slate-600"
                  }`}
                >
                  {variant.is_active ? "active" : "inactive"}
                </span>
              </li>
            ))}
          </ul>
          {!ready && (
            <div className="mt-4 rounded-lg border border-slate-800 bg-slate-950/40 p-4 text-sm">
              <p className="text-slate-300">A/B lab is waiting for a second active arm.</p>
              <p className="mt-2 text-xs text-slate-500">
                Only <span className="text-slate-300">{active[0]?.name || "control"}</span> is
                active. Activate one challenger in Django admin when you are ready to spend
                roughly double inference cost, run a cycle, then wait for the hourly{" "}
                <code className="text-slate-400">build-ab-pairs</code> task.
                {inactive.length > 0 && (
                  <>
                    {" "}
                    Inactive arms ready to enable:{" "}
                    {inactive.map((row) => row.name).join(", ")}.
                  </>
                )}
              </p>
            </div>
          )}
        </>
      )}
    </Card>
  );
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
          <TableScroll>
            <table className="w-full min-w-[240px] text-sm">
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
          </TableScroll>
        )}
      </Card>

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
  if (!(await currentStaffUser())) {
    return (
      <Card className="p-10 text-center">
        <p className="text-slate-300">Staff access required</p>
        <p className="mt-2 text-sm text-slate-500">
          A/B judgements are shared experiment evidence and are reserved for staff reviewers.
        </p>
      </Card>
    );
  }
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
        <AsyncPanel label="Variant setup" fallback={<Skeleton className="h-40 w-full" />}>
          <VariantSetup />
        </AsyncPanel>

        <AsyncPanel label="Standings" fallback={<Skeleton className="h-56 w-full" />}>
          <Standings />
        </AsyncPanel>

        <Card className="p-4 text-xs text-slate-500">
          <SectionTitle>How pairs are made</SectionTitle>
          <ol className="mt-2 list-decimal space-y-1.5 pl-4">
            <li>
              <code className="text-slate-400">seed_variants</code> creates control (active)
              plus inactive challengers — safe on a fresh deploy, no API calls.
            </li>
            <li>
              When ready, activate a second variant in admin. Each active arm answers every
              article (~double cost per cycle).
            </li>
            <li>
              Run inference, then wait for the hourly{" "}
              <code className="text-slate-400">build-ab-pairs</code> task to pair articles
              both arms evaluated.
            </li>
          </ol>
        </Card>
      </aside>
    </div>
  );
}
