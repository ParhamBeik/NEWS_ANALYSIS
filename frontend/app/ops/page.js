import { Card, Metric, SectionTitle } from "@/components/primitives";
import { apiGet } from "@/lib/api";
import { money, number, percent, tehranTime } from "@/lib/display";

export const metadata = { title: "Ops · News Intelligence" };
export const dynamic = "force-dynamic";

const HEALTH_TONE = {
  healthy: "text-emerald-400",
  degraded: "text-amber-400",
  failing: "text-rose-400",
};

function Bar({ value, max, tone = "bg-emerald-500" }) {
  const width = max ? Math.max(2, Math.round((value / max) * 100)) : 0;
  return (
    <div className="h-1.5 w-full rounded bg-slate-800">
      <div className={`h-1.5 rounded ${tone}`} style={{ width: `${width}%` }} />
    </div>
  );
}

export default async function OpsPage({ searchParams }) {
  const params = await searchParams;
  const days = params?.days || 14;
  const ops = await apiGet(`/api/ops/?days=${days}`);

  const { funnel, budget } = ops;
  const maxCost = Math.max(...ops.cost_by_day.map((row) => row.cost), 0.0001);
  const overBudget = budget.spent_today_usd > budget.daily_ceiling_usd;

  const failures = ops.node_outcomes.filter(
    (row) => !["success", "skipped"].includes(row.status),
  );

  return (
    <>
      <div className="mb-5 flex flex-wrap items-end justify-between gap-3">
        <div>
          <h1 className="text-2xl font-semibold text-slate-100">Operations</h1>
          <p className="mt-1 text-sm text-slate-500">
            Last {ops.window_days} days. Throughput and spend on the same page, because
            throughput alone lets a runaway run look healthy.
          </p>
        </div>
        <div className="flex gap-1 text-xs">
          {[1, 7, 14, 30].map((option) => (
            <a
              key={option}
              href={`/ops?days=${option}`}
              className={`rounded-md px-2 py-1 ${
                String(days) === String(option)
                  ? "bg-slate-800 text-slate-100"
                  : "text-slate-500 hover:bg-slate-900"
              }`}
            >
              {option}d
            </a>
          ))}
        </div>
      </div>

      <div className="mb-6 grid grid-cols-2 gap-3 md:grid-cols-4">
        <Metric
          label="Spend today"
          value={money(budget.spent_today_usd)}
          hint={`ceiling ${money(budget.daily_ceiling_usd, 2)}`}
          tone={overBudget ? "text-rose-400" : ""}
        />
        <Metric label="Run ceiling" value={money(budget.run_ceiling_usd, 2)} />
        <Metric
          label="Dead letters"
          value={number(ops.dead_letters.reduce((total, row) => total + row.count, 0))}
          tone={ops.dead_letters.length ? "text-amber-400" : ""}
          hint="unresolved"
        />
        <Metric
          label="Duplicates collapsed"
          value={number(funnel.duplicates)}
          hint={`of ${number(funnel.fetched)} fetched`}
        />
      </div>

      <div className="grid gap-6 lg:grid-cols-2">
        <Card className="p-4">
          <SectionTitle hint="each stage is a subset of the one above">Funnel</SectionTitle>
          <div className="space-y-2.5">
            {[
              ["Fetched", funnel.fetched, "bg-slate-500"],
              ["Canonical (after dedupe)", funnel.canonical, "bg-sky-500"],
              ["Classified", funnel.classified, "bg-violet-500"],
              ["Evaluated", funnel.evaluated, "bg-emerald-500"],
            ].map(([label, value, tone]) => (
              <div key={label}>
                <div className="mb-1 flex justify-between text-xs">
                  <span className="text-slate-400">{label}</span>
                  <span className="tabular text-slate-300">
                    {number(value)}{" "}
                    <span className="text-slate-600">
                      {funnel.fetched ? percent(value / funnel.fetched, 0) : ""}
                    </span>
                  </span>
                </div>
                <Bar value={value} max={funnel.fetched} tone={tone} />
              </div>
            ))}
          </div>
          <div className="mt-4 grid grid-cols-2 gap-3 border-t border-slate-800 pt-3 text-xs">
            <div>
              <span className="text-slate-500">Prefiltered (stored, unanalysed)</span>
              <div className="tabular text-lg text-slate-200">{number(funnel.prefiltered)}</div>
            </div>
            <div>
              <span className="text-slate-500">Quality-rejected</span>
              <div className="tabular text-lg text-slate-200">
                {number(funnel.quality_rejected)}
              </div>
            </div>
          </div>
        </Card>

        <Card className="p-4">
          <SectionTitle hint="from the provider's own reported usage">
            Cost per day
          </SectionTitle>
          {ops.cost_by_day.length === 0 ? (
            <p className="text-sm text-slate-500">No provider calls in this window.</p>
          ) : (
            <div className="space-y-1.5">
              {ops.cost_by_day.map((row) => (
                <div key={row.day} className="flex items-center gap-3 text-xs">
                  <span className="w-20 shrink-0 tabular text-slate-500">{row.day}</span>
                  <Bar
                    value={row.cost}
                    max={maxCost}
                    tone={row.cost > budget.daily_ceiling_usd ? "bg-rose-500" : "bg-emerald-500"}
                  />
                  <span className="w-16 shrink-0 text-right tabular text-slate-300">
                    {money(row.cost)}
                  </span>
                  <span className="w-12 shrink-0 text-right tabular text-slate-600">
                    {number(row.calls)}
                  </span>
                </div>
              ))}
            </div>
          )}
        </Card>

        <Card className="p-4">
          <SectionTitle hint="reachability is measured, not assumed">
            Source health
          </SectionTitle>
          <table className="w-full text-sm">
            <tbody>
              {ops.sources.map((source) => (
                <tr key={source.name} className="border-t border-slate-800">
                  <td className="py-2">
                    <div className="text-slate-200">{source.name}</div>
                    <div className="text-[11px] text-slate-600">
                      {source.strategy} · tier {source.tier}
                      {!source.supports_backfill && " · no archive backfill"}
                    </div>
                  </td>
                  <td className="py-2 text-right">
                    <div className={HEALTH_TONE[source.health_status] || "text-slate-400"}>
                      {source.enabled ? source.health_status : "disabled"}
                    </div>
                    <div className="text-[11px] text-slate-600">
                      {tehranTime(source.last_success_at)}
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </Card>

        <Card className="p-4">
          <SectionTitle hint="a schema failure means no verdict at all">
            Node outcomes
          </SectionTitle>
          {failures.length === 0 ? (
            <p className="text-sm text-emerald-400">No failures in this window.</p>
          ) : (
            <table className="w-full text-sm">
              <tbody>
                {failures.map((row) => (
                  <tr key={`${row.node}-${row.status}`} className="border-t border-slate-800">
                    <td className="py-1.5 text-slate-300">{row.node}</td>
                    <td className="py-1.5 text-slate-500">{row.status}</td>
                    <td className="py-1.5 text-right tabular text-amber-400">{row.count}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
          {ops.dead_letters.length > 0 && (
            <>
              <div className="mt-4 mb-1 text-xs uppercase tracking-wider text-slate-600">
                Quarantined
              </div>
              {ops.dead_letters.map((row) => (
                <div
                  key={`${row.node}-${row.error_class}`}
                  className="flex justify-between border-t border-slate-800 py-1.5 text-xs"
                >
                  <span className="text-slate-400">
                    {row.node} · {row.error_class}
                  </span>
                  <span className="tabular text-slate-300">{row.count}</span>
                </div>
              ))}
            </>
          )}
        </Card>

        {/* The prefilter is the one change that can silently lose a story, so its effect is
            reported rather than assumed. `articles` is the evidence you'd need to justify
            turning a rule back off. */}
        <Card className="p-4">
          <SectionTitle hint="the only change that can silently lose a story">
            Prefilter audit
          </SectionTitle>
          {ops.prefilter_rules.length === 0 ? (
            <p className="text-sm text-slate-500">
              No rules defined. Every article reaches inference.
            </p>
          ) : (
            <table className="w-full text-sm">
              <tbody>
                {ops.prefilter_rules.map((rule) => (
                  <tr
                    key={`${rule.source}-${rule.native_category}`}
                    className="border-t border-slate-800"
                  >
                    <td className="py-1.5">
                      <span className="text-slate-300">{rule.source}</span>
                      <span className="text-slate-600"> / {rule.native_category}</span>
                    </td>
                    <td className="py-1.5 text-right tabular text-slate-400">
                      {number(rule.articles)}
                    </td>
                    <td className="py-1.5 pl-3 text-right">
                      <span
                        className={rule.enabled ? "text-amber-400" : "text-slate-600"}
                      >
                        {rule.enabled ? "skipping" : "off"}
                      </span>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </Card>

        <Card className="p-4">
          <SectionTitle hint="tier is the early warning for a site redesign">
            Extraction tiers
          </SectionTitle>
          <div className="space-y-1.5">
            {ops.extraction_tiers.map((row) => (
              <div key={row.extraction_tier} className="flex items-center gap-3 text-xs">
                <span className="w-20 shrink-0 text-slate-400">
                  {row.extraction_tier || "unknown"}
                </span>
                <Bar
                  value={row.count}
                  max={Math.max(...ops.extraction_tiers.map((tier) => tier.count), 1)}
                  tone={row.extraction_tier === "feed" ? "bg-amber-500" : "bg-sky-500"}
                />
                <span className="w-10 shrink-0 text-right tabular text-slate-300">
                  {row.count}
                </span>
              </div>
            ))}
          </div>
          <p className="mt-3 text-[11px] text-slate-600">
            A &ldquo;feed&rdquo; tier article is ~220 characters of RSS because the outlet
            gates its article pages behind Cloudflare — not because the crawler failed.
          </p>
        </Card>

        <Card className="p-4 lg:col-span-2">
          <SectionTitle>Recent runs</SectionTitle>
          <table className="w-full text-sm">
            <thead>
              <tr className="text-left text-[11px] uppercase tracking-wider text-slate-600">
                <th className="pb-1">Run</th>
                <th className="pb-1">Started</th>
                <th className="pb-1 text-right">Fetched</th>
                <th className="pb-1 text-right">Processed</th>
                <th className="pb-1 text-right">Cost</th>
                <th className="pb-1 text-right">Status</th>
              </tr>
            </thead>
            <tbody>
              {ops.recent_runs.map((run) => (
                <tr key={run.run_id} className="border-t border-slate-800">
                  <td className="py-1.5 font-mono text-xs text-slate-400">{run.run_id}</td>
                  <td className="py-1.5 text-xs text-slate-500">
                    {tehranTime(run.started_at)}
                  </td>
                  <td className="py-1.5 text-right tabular">{run.articles_fetched}</td>
                  <td className="py-1.5 text-right tabular">{run.articles_processed}</td>
                  <td className="py-1.5 text-right tabular">{money(run.cost_usd)}</td>
                  <td
                    className={`py-1.5 text-right text-xs ${
                      run.status === "failed" ? "text-rose-400" : "text-slate-400"
                    }`}
                    title={run.error || ""}
                  >
                    {run.status}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </Card>
      </div>
    </>
  );
}
