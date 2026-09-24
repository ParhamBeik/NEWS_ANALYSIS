import { Card, CircuitBanner, Metric, QueryError, SectionTitle, TableScroll } from "@/components/primitives";
import { ApiError, apiGet } from "@/lib/api";
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

/**
 * Backup freshness.
 *
 * A backup job that stopped three weeks ago looks exactly like one that is working, right
 * up until the restore that discovers otherwise. The age of the newest VERIFIED dump is
 * the only number that distinguishes them, so it gets a card rather than a log line, and
 * it turns amber before it turns into an incident.
 */
function BackupHealth({ backups }) {
  const stale = backups.age_hours === null || backups.age_hours > 36;
  return (
    <Card className="p-4">
      <SectionTitle hint="a silent backup failure is invisible until the restore">
        Backups
      </SectionTitle>
      {!backups.configured ? (
        <p className="text-sm text-amber-400">
          No backup directory is mounted. The database holds every human review label, and
          nothing here is dumping it — see the restore runbook in the README.
        </p>
      ) : (
        <div className="flex items-baseline justify-between gap-4">
          <div>
            <div
              className={`text-2xl font-semibold tabular ${
                stale ? "text-rose-400" : "text-emerald-400"
              }`}
            >
              {backups.age_hours === null ? "never" : `${backups.age_hours}h ago`}
            </div>
            <div className="mt-1 text-xs text-slate-500">
              {backups.last_success_at
                ? `last verified dump ${tehranTime(backups.last_success_at)}`
                : "no dump has completed yet"}
            </div>
          </div>
          <div className="text-right">
            <div className="tabular text-lg text-slate-200">{number(backups.retained)}</div>
            <div className="text-xs text-slate-500">retained</div>
          </div>
        </div>
      )}
      {backups.configured && stale && backups.age_hours !== null && (
        <p className="mt-3 text-xs text-rose-300/80">
          Expected a dump every 24h. Check <span className="tabular">docker compose logs
          backup</span>.
        </p>
      )}
      <p className={`mt-3 text-xs ${
        backups.offsite_age_hours == null || backups.offsite_age_hours > 36
          ? "text-rose-300" : "text-emerald-400"
      }`}>
        Off-host copy: {backups.offsite_age_hours == null
          ? "not verified" : `${backups.offsite_age_hours}h ago`}
      </p>
    </Card>
  );
}

export default async function OpsPage({ searchParams }) {
  const params = await searchParams;
  const days = params?.days || 14;
  let ops;
  try {
    ops = await apiGet(`/api/ops/?days=${days}`);
  } catch (error) {
    if (error instanceof ApiError && error.status === 400) {
      return (
        <QueryError title="Invalid time window.">
          Choose one of 1, 7, 14, or 30 days.
        </QueryError>
      );
    }
    throw error;
  }

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
        <div className="flex flex-wrap gap-1 text-xs">
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

      <CircuitBanner circuit={ops.provider_circuit} />

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
                <div className="mb-1 flex justify-between gap-2 text-xs">
                  <span className="min-w-0 text-slate-400">{label}</span>
                  <span className="shrink-0 tabular text-slate-300">
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
                <div key={row.day} className="flex items-center gap-2 text-xs sm:gap-3">
                  <span className="w-16 shrink-0 tabular text-slate-500 sm:w-20">{row.day}</span>
                  <Bar
                    value={row.cost}
                    max={maxCost}
                    tone={row.cost > budget.daily_ceiling_usd ? "bg-rose-500" : "bg-emerald-500"}
                  />
                  <span className="w-14 shrink-0 text-right tabular text-slate-300 sm:w-16">
                    {money(row.cost)}
                  </span>
                  <span className="hidden w-12 shrink-0 text-right tabular text-slate-600 sm:inline">
                    {number(row.calls)}
                  </span>
                </div>
              ))}
            </div>
          )}
        </Card>

        <BackupHealth backups={ops.backups} />

        <Card className="p-4">
          <SectionTitle hint="reachability is measured, not assumed">
            Source health
          </SectionTitle>
          <TableScroll>
            <table className="w-full min-w-[280px] text-sm">
              <tbody>
                {ops.sources.map((source) => (
                  <tr key={source.name} className="border-t border-slate-800">
                    <td className="py-2 pr-2">
                      <div className="text-slate-200">{source.name}</div>
                      <div className="text-[11px] leading-snug text-slate-600">
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
          </TableScroll>
        </Card>

        <Card className="p-4">
          <SectionTitle hint="a schema failure means no verdict at all">
            Node outcomes
          </SectionTitle>
          {failures.length === 0 ? (
            <p className="text-sm text-emerald-400">No failures in this window.</p>
          ) : (
            <TableScroll>
              <table className="w-full min-w-[240px] text-sm">
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
            </TableScroll>
          )}
          {ops.dead_letters.length > 0 && (
            <>
              <div className="mt-4 mb-1 text-xs uppercase tracking-wider text-slate-600">
                Quarantined
              </div>
              {ops.dead_letters.map((row) => (
                <div
                  key={`${row.node}-${row.error_class}`}
                  className="flex justify-between gap-2 border-t border-slate-800 py-1.5 text-xs"
                >
                  <span className="min-w-0 text-slate-400">
                    {row.node} · {row.error_class}
                  </span>
                  <span className="shrink-0 tabular text-slate-300">{row.count}</span>
                </div>
              ))}
            </>
          )}
        </Card>

        <Card className="p-4">
          <SectionTitle hint="the only change that can silently lose a story">
            Prefilter audit
          </SectionTitle>
          {ops.prefilter_rules.length === 0 ? (
            <p className="text-sm text-slate-500">
              No rules defined. Every article reaches inference.
            </p>
          ) : (
            <TableScroll>
              <table className="w-full min-w-[280px] text-sm">
                <tbody>
                  {ops.prefilter_rules.map((rule) => (
                    <tr
                      key={`${rule.source}-${rule.native_category}`}
                      className="border-t border-slate-800"
                    >
                      <td className="py-1.5 pr-2">
                        <span className="text-slate-300">{rule.source}</span>
                        <span className="text-slate-600"> / {rule.native_category}</span>
                      </td>
                      <td className="py-1.5 text-right tabular text-slate-400">
                        {number(rule.articles)}
                      </td>
                      <td className="py-1.5 pl-2 text-right sm:pl-3">
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
            </TableScroll>
          )}
        </Card>

        <Card className="p-4">
          <SectionTitle hint="tier is the early warning for a site redesign">
            Extraction tiers
          </SectionTitle>
          <div className="space-y-1.5">
            {ops.extraction_tiers.map((row) => (
              <div key={row.extraction_tier} className="flex items-center gap-2 text-xs sm:gap-3">
                <span className="w-16 shrink-0 text-slate-400 sm:w-20">
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
          <TableScroll>
            <table className="w-full min-w-[520px] text-sm">
              <thead>
                <tr className="text-left text-[11px] uppercase tracking-wider text-slate-600">
                  <th className="pb-1">Run</th>
                  <th className="pb-1">Started</th>
                  <th className="hidden pb-1 text-right sm:table-cell">Fetched</th>
                  <th className="hidden pb-1 text-right md:table-cell">Processed</th>
                  <th className="pb-1 text-right">Cost</th>
                  <th className="pb-1 text-right">Status</th>
                </tr>
              </thead>
              <tbody>
                {ops.recent_runs.map((run) => (
                  <tr key={run.run_id} className="border-t border-slate-800">
                    <td className="max-w-[9rem] truncate py-1.5 font-mono text-xs text-slate-400 sm:max-w-none">
                      {run.run_id}
                    </td>
                    <td className="whitespace-nowrap py-1.5 text-xs text-slate-500">
                      {tehranTime(run.started_at)}
                    </td>
                    <td className="hidden py-1.5 text-right tabular sm:table-cell">
                      {run.articles_fetched}
                    </td>
                    <td className="hidden py-1.5 text-right tabular md:table-cell">
                      {run.articles_processed}
                    </td>
                    <td className="py-1.5 text-right tabular">{money(run.cost_usd)}</td>
                    <td
                      className={`py-1.5 text-right text-xs ${
                        run.status === "failed" ? "text-rose-400" : "text-slate-400"
                      }`}
                      aria-label={`Run ${run.status}`}
                    >
                      {run.status}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </TableScroll>
        </Card>
      </div>
    </>
  );
}
