import { Card, Metric, SectionTitle, StackedTable } from "@/components/primitives";
import { money, number, percent, tehranTime } from "@/lib/display";

/** Staff-only panels on /ops, fed by /api/ops/staff/. Labels follow the reader's language. */

const PAUSED = {
  wallet_empty: ["AI paused: provider wallet empty", "هوش مصنوعی متوقف است: کیف پول ارائه‌دهنده خالی است"],
  circuit_open: ["AI paused: provider circuit open", "هوش مصنوعی متوقف است: مدار ارائه‌دهنده باز است"],
  monthly_budget: ["AI paused: monthly budget reached", "هوش مصنوعی متوقف است: سقف بودجه ماهانه پر شده"],
  daily_budget: ["AI paused: daily budget reached", "هوش مصنوعی متوقف است: سقف بودجه روزانه پر شده"],
};

const STAGE = {
  jev: ["Decisions (Jev)", "تصمیم (Jev)"],
  brief: ["Briefs", "خلاصه‌ها"],
  storyline: ["Storylines", "روایت‌ها"],
};

const FAILURE = {
  budget: ["budget", "بودجه"],
  fatal: ["auth/fatal", "احراز/مهلک"],
  permanent: ["permanent", "دائمی"],
  transient: ["transient", "گذرا"],
  invalid_answer: ["invalid answer", "پاسخ نامعتبر"],
  other: ["other", "سایر"],
};

const ERROR_CLASS = {
  network: ["network", "شبکه"],
  blocked: ["blocked", "مسدود"],
  parse: ["parse", "تجزیه"],
  rate_limit: ["rate limit", "محدودیت نرخ"],
  gone: ["gone", "حذف‌شده"],
  provider: ["provider", "ارائه‌دهنده"],
};

function share(spent, ceiling) {
  return ceiling ? spent / ceiling : null;
}

function spendTone(spent, ceiling) {
  const ratio = share(spent, ceiling);
  if (ratio === null) return "";
  return ratio >= 1 ? "text-rose-400" : ratio >= 0.8 ? "text-amber-400" : "";
}

export function AiPausedBanner({ ai, tr }) {
  const text = PAUSED[ai.paused];
  if (!text) return null;
  return (
    <Card role="alert" className="mb-6 border-rose-900/60 bg-rose-950/20 p-4 text-sm text-rose-200/90">
      <p className="font-medium">{tr(...text)}</p>
      {ai.circuit?.reason && <p className="mt-1 break-words text-xs opacity-80">{ai.circuit.reason}</p>}
    </Card>
  );
}

export function AiCostPanel({ ai, tr }) {
  const failures = Object.entries(ai.failures_7d).filter(([, count]) => count > 0);
  return (
    <Card className="p-4 lg:col-span-2">
      <SectionTitle hint={tr("UTC day and month, as the budget guard counts them", "روز و ماه UTC، همان‌گونه که محافظ بودجه می‌شمارد")}>
        {tr("AI cost", "هزینه هوش مصنوعی")}
      </SectionTitle>
      <div className="mb-4 grid grid-cols-2 gap-3 md:grid-cols-4">
        <Metric label={tr("Month to date", "از ابتدای ماه")} value={money(ai.month.spent_usd, 2)}
          hint={`${tr("of", "از")} ${money(ai.month.ceiling_usd, 2)} · ${percent(share(ai.month.spent_usd, ai.month.ceiling_usd), 0)}`}
          tone={spendTone(ai.month.spent_usd, ai.month.ceiling_usd)} />
        <Metric label={tr("Today", "امروز")} value={money(ai.today.spent_usd, 2)}
          hint={`${tr("of", "از")} ${money(ai.today.ceiling_usd, 2)} · ${percent(share(ai.today.spent_usd, ai.today.ceiling_usd), 0)}`}
          tone={spendTone(ai.today.spent_usd, ai.today.ceiling_usd)} />
        <Metric label={tr("Provider circuit", "مدار ارائه‌دهنده")} value={ai.circuit.state}
          tone={ai.circuit.state === "closed" ? "text-emerald-400" : "text-rose-400"}
          hint={ai.circuit.next_probe_at ? `${tr("next probe", "آزمون بعدی")} ${tehranTime(ai.circuit.next_probe_at)}` : null} />
        <Metric label={tr("Failures, 7 days", "خطاها، ۷ روز")}
          value={number(failures.reduce((total, [, count]) => total + count, 0))}
          tone={failures.length ? "text-amber-400" : ""}
          hint={failures.map(([kind, count]) => `${tr(...(FAILURE[kind] || [kind, kind]))} ${count}`).join(" · ") || null} />
      </div>
      <div className="grid gap-6 md:grid-cols-2">
        <div>
          <h3 className="mb-2 text-xs text-slate-500">{tr("By stage", "بر اساس مرحله")}</h3>
          <StackedTable
            rowKey={(row) => row.stage}
            rows={ai.by_stage}
            columns={[
              { key: "stage", label: tr("Stage", "مرحله"), render: (row) => tr(...(STAGE[row.stage] || [row.stage, row.stage])) },
              { key: "calls", label: tr("Calls", "فراخوانی"), end: true, render: (row) => number(row.calls) },
              { key: "today", label: tr("Today", "امروز"), end: true, render: (row) => money(row.today_usd) },
              { key: "month", label: tr("Month", "ماه"), end: true, render: (row) => money(row.cost_usd) },
            ]}
          />
          <h3 className="mb-2 mt-4 text-xs text-slate-500">{tr("By provider", "بر اساس ارائه‌دهنده")}</h3>
          {ai.by_provider.length === 0 ? (
            <p className="text-sm text-slate-500">{tr("No paid calls this month.", "این ماه فراخوانی پولی نبوده است.")}</p>
          ) : (
            <StackedTable
              rowKey={(row) => row.provider}
              rows={ai.by_provider}
              columns={[
                { key: "provider", label: tr("Provider", "ارائه‌دهنده") },
                { key: "calls", label: tr("Calls", "فراخوانی"), end: true, render: (row) => number(row.calls) },
                { key: "month", label: tr("Month", "ماه"), end: true, render: (row) => money(row.cost_usd) },
              ]}
            />
          )}
        </div>
        <div>
          <h3 className="mb-2 text-xs text-slate-500">{tr("Calls and failures, 7 days (UTC)", "فراخوانی و خطا، ۷ روز (UTC)")}</h3>
          <StackedTable
            rowKey={(row) => row.day}
            rows={[...ai.daily].reverse()}
            columns={[
              { key: "day", label: tr("Day", "روز"), className: "tabular text-slate-400" },
              { key: "calls", label: tr("Calls", "فراخوانی"), end: true, render: (row) => number(row.calls) },
              {
                key: "failures", label: tr("Failures", "خطا"), end: true,
                render: (row) => {
                  const entries = Object.entries(row.failures);
                  if (!entries.length) return <span className="text-slate-600">0</span>;
                  return <span className="text-amber-400">
                    {entries.map(([kind, count]) => `${tr(...(FAILURE[kind] || [kind, kind]))} ${count}`).join(" · ")}
                  </span>;
                },
              },
            ]}
          />
        </div>
      </div>
    </Card>
  );
}

export function CrawlErrorsPanel({ errors, tr }) {
  const classLabel = (name) => tr(...(ERROR_CLASS[name] || [name, name]));
  const active = errors.classes.filter((name) => errors.totals[name]?.last_7d);
  return (
    <Card className="p-4">
      <SectionTitle hint={tr("failed crawl attempts", "تلاش‌های ناموفق گردآوری")}>
        {tr("Errors by cause", "خطاها بر اساس علت")}
      </SectionTitle>
      {errors.rows.length === 0 ? (
        <p className="text-sm text-emerald-400">{tr("No crawl errors in 7 days.", "در ۷ روز گذشته خطای گردآوری نبوده است.")}</p>
      ) : (
        <>
          <div className="mb-3 flex flex-wrap gap-2 text-xs">
            {active.map((name) => (
              <span key={name} className="rounded-md border border-slate-800 px-2 py-0.5 text-slate-300">
                {classLabel(name)}: {number(errors.totals[name].last_24h)} / {number(errors.totals[name].last_7d)}
              </span>
            ))}
          </div>
          <StackedTable
            rowKey={(row) => `${row.source}-${row.error_class}`}
            rows={errors.rows}
            columns={[
              { key: "display_name", label: tr("Source", "منبع"), className: "text-slate-300" },
              { key: "error_class", label: tr("Cause", "علت"), className: "text-xs text-slate-400", render: (row) => classLabel(row.error_class) },
              { key: "last_24h", label: tr("24h", "۲۴ ساعت"), end: true, render: (row) => <span className={row.last_24h ? "text-amber-400" : "text-slate-600"}>{number(row.last_24h)}</span> },
              { key: "last_7d", label: tr("7d", "۷ روز"), end: true, render: (row) => number(row.last_7d) },
            ]}
          />
        </>
      )}
    </Card>
  );
}

function SloRow({ label, result, tr }) {
  const measured = result.passed + result.failed;
  return (
    <div className="border-t border-slate-800 py-2 first:border-0">
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <span className="text-sm text-slate-300">{label}</span>
        <span className={`text-sm tabular ${result.failed ? "text-rose-400" : "text-emerald-400"}`}>
          {measured ? percent(result.passed / measured, 0) : "—"}
        </span>
      </div>
      <div className="mt-1 flex flex-wrap gap-3 text-xs text-slate-500">
        <span>{tr("pass", "موفق")} {number(result.passed)}</span>
        <span className={result.failed ? "text-rose-400" : ""}>{tr("miss", "ناموفق")} {number(result.failed)}</span>
        {result.pending !== undefined && <span>{tr("pending", "در انتظار")} {number(result.pending)}</span>}
      </div>
    </div>
  );
}

export function FreshnessPanel({ freshness, gaps, tr }) {
  const { discovery, brief } = freshness;
  return (
    <Card className="p-4">
      <SectionTitle hint={tr(`last ${freshness.window_hours} hours`, `${freshness.window_hours} ساعت گذشته`)}>
        {tr("Freshness SLO", "هدف تازگی")}
      </SectionTitle>
      <SloRow tr={tr} result={discovery}
        label={tr(`Priority sources discovered ≤ ${discovery.target_minutes} min`, `کشف خبر منابع اولویت‌دار ≤ ${discovery.target_minutes} دقیقه`)} />
      {discovery.misses_by_source.length > 0 && (
        <p className="mb-1 text-[11px] text-slate-500">
          {discovery.misses_by_source.map((row) => `${row.source_id} ${row.count}`).join(" · ")}
        </p>
      )}
      <SloRow tr={tr} result={brief}
        label={tr(`Tier 4+ events briefed ≤ ${brief.target_minutes} min`, `خلاصه رویدادهای سطح ۴+ ≤ ${brief.target_minutes} دقیقه`)} />
      {brief.misses.map((miss) => (
        <a key={miss.event} href={`/events/${miss.event}`}
          className="flex justify-between gap-3 py-0.5 text-[11px] text-slate-500 hover:text-slate-300">
          <bdi className="min-w-0 truncate" dir="auto">{miss.title || `#${miss.event}`}</bdi>
          <span className="shrink-0 tabular">
            {miss.minutes} {tr("min", "دقیقه")}{miss.brief_visible ? "" : ` · ${tr("no brief", "بدون خلاصه")}`}
          </span>
        </a>
      ))}
      <div className="mt-3 border-t border-slate-800 pt-2">
        <div className="text-xs text-slate-500">{tr("Priority sources with a gap over 30 min", "منابع اولویت‌دار با وقفه بیش از ۳۰ دقیقه")}</div>
        {gaps.length === 0 ? (
          <p className="mt-1 text-sm text-emerald-400">{tr("None", "هیچ")}</p>
        ) : gaps.map((gap) => (
          <div key={gap.source} className="mt-1 flex flex-wrap justify-between gap-2 text-sm">
            <span className="text-slate-300">{gap.display_name}</span>
            <span className="text-xs text-rose-400">
              {gap.state}{gap.error_class ? ` · ${gap.error_class}` : ""} · {gap.since ? tehranTime(gap.since) : tr("never covered", "هرگز پوشش نداشته")}
            </span>
          </div>
        ))}
      </div>
    </Card>
  );
}
