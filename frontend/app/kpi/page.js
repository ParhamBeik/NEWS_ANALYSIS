import { Card, Metric, SectionTitle } from "@/components/primitives";
import { apiGet } from "@/lib/api";
import { AXIS_LABEL, number, percent } from "@/lib/display";

export const metadata = { title: "Quality · News Intelligence" };
export const dynamic = "force-dynamic";

export default async function KPIPage() {
  const kpi = await apiGet("/api/kpi/");
  const confusion = kpi.notify_confusion;
  const missed = confusion.fn;

  return (
    <>
      <h1 className="mb-1 text-2xl font-semibold text-slate-100">Quality</h1>
      <p className="mb-6 text-sm text-slate-500">
        Two independent questions: does the model agree with a human, and was it right about
        the gold price? Neither is throughput, and neither can be inferred from the other.
      </p>

      <div className="mb-6 grid grid-cols-2 gap-3 md:grid-cols-4">
        <Metric
          label="Human labels"
          value={number(kpi.labelled_articles)}
          hint="approved only"
        />
        <Metric
          label="Category agreement"
          value={percent(kpi.category_agreement.rate)}
          hint={`${kpi.category_agreement.agreed}/${kpi.category_agreement.compared}`}
        />
        <Metric
          label="Notify recall"
          value={percent(kpi.notify_recall)}
          tone={missed > 0 ? "text-rose-400" : "text-emerald-400"}
          hint={`${missed} missed alert${missed === 1 ? "" : "s"}`}
        />
        <Metric
          label="Directional accuracy"
          value={percent(kpi.backtest.directional_accuracy)}
          hint={`${number(kpi.backtest.scored_predictions)} scored`}
        />
      </div>

      {kpi.labelled_articles === 0 && (
        <Card className="mb-6 border-amber-900/50 bg-amber-950/20 p-4 text-sm text-amber-200/90">
          No approved human labels yet, so every agreement figure below is empty by
          construction rather than bad. Label a few articles on the Review page — the golden
          set cannot be seeded from the model&rsquo;s own answers, or it would measure the
          model against itself and report perfect agreement.
        </Card>
      )}

      <div className="grid gap-6 lg:grid-cols-2">
        <Card className="p-4">
          <SectionTitle hint="both sides assessed only">Axis agreement</SectionTitle>
          <table className="w-full text-sm">
            <thead>
              <tr className="text-left text-[11px] uppercase tracking-wider text-slate-600">
                <th className="pb-1">Axis</th>
                <th className="pb-1 text-right">Exact</th>
                <th className="pb-1 text-right">±1 level</th>
                <th className="pb-1 text-right">n</th>
              </tr>
            </thead>
            <tbody>
              {kpi.axis_agreement.map((row) => (
                <tr key={row.axis} className="border-t border-slate-800">
                  <td className="py-2 text-slate-300">{AXIS_LABEL[row.axis] || row.axis}</td>
                  <td className="py-2 text-right tabular text-slate-200">
                    {percent(row.exact_rate)}
                  </td>
                  <td className="py-2 text-right tabular text-emerald-400">
                    {percent(row.within_one_rate)}
                  </td>
                  <td className="py-2 text-right tabular text-slate-600">{row.compared}</td>
                </tr>
              ))}
            </tbody>
          </table>
          <p className="mt-3 text-[11px] text-slate-600">
            The scale is ordinal, so ±1 is the honest headline: «زیاد» against «خیلی زیاد» is
            a far smaller error than «زیاد» against «خیلی کم», and exact-match hides that.
            An axis the human left blank is not counted as a disagreement — that would punish
            the model for the reviewer&rsquo;s omission and let the metric drift with fatigue.
          </p>
        </Card>

        <Card className="p-4">
          <SectionTitle hint="the failure this whole system exists to prevent">
            Notify decision
          </SectionTitle>
          <div className="grid grid-cols-2 gap-2 text-center">
            {[
              ["True positive", confusion.tp, "text-emerald-400", "both said notify"],
              ["False negative", confusion.fn, "text-rose-400", "human said notify, model was silent"],
              ["False positive", confusion.fp, "text-amber-400", "model cried wolf"],
              ["True negative", confusion.tn, "text-slate-400", "both said quiet"],
            ].map(([label, value, tone, hint]) => (
              <div key={label} className="rounded-lg border border-slate-800 p-3">
                <div className={`tabular text-2xl ${tone}`}>{number(value)}</div>
                <div className="text-xs text-slate-400">{label}</div>
                <div className="mt-0.5 text-[10px] text-slate-600">{hint}</div>
              </div>
            ))}
          </div>
          <p className="mt-3 text-[11px] text-slate-600">
            False negatives get their own number instead of being folded into an accuracy
            figure. On a mostly-quiet corpus, accuracy would sit near 95% while every single
            alert was being missed — which is precisely what the legacy pipeline did:
            0 of 488.
          </p>
        </Card>

        {kpi.agreement_by_stratum.length > 0 && (
          <Card className="p-4">
            <SectionTitle hint="the review sample is not random">
              Agreement by stratum
            </SectionTitle>
            <table className="w-full text-sm">
              <tbody>
                {kpi.agreement_by_stratum.map((row) => (
                  <tr key={row.stratum} className="border-t border-slate-800">
                    <td className="py-1.5 text-slate-300">{row.stratum}</td>
                    <td className="py-1.5 text-right tabular text-slate-200">
                      {percent(row.rate)}
                    </td>
                    <td className="py-1.5 text-right tabular text-slate-600">
                      {row.compared}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
            <p className="mt-3 text-[11px] text-slate-600">
              Cases are queued because they were disagreements or `other` verdicts, so one
              blended number would understate real-world agreement. Read the strata, not the
              average.
            </p>
          </Card>
        )}

        <Card className="p-4">
          <SectionTitle hint="predictions against realised prices">Gold back-test</SectionTitle>
          {kpi.backtest.scored_predictions === 0 ? (
            <p className="text-sm text-slate-500">
              No scored predictions yet. Outcomes appear once the trading-day window has
              elapsed and prices exist on both ends of it.
            </p>
          ) : (
            <>
              <table className="w-full text-sm">
                <thead>
                  <tr className="text-left text-[11px] uppercase tracking-wider text-slate-600">
                    <th className="pb-1">Window</th>
                    <th className="pb-1 text-right">Correct</th>
                    <th className="pb-1 text-right">n</th>
                  </tr>
                </thead>
                <tbody>
                  {kpi.backtest.by_window.map((row) => (
                    <tr key={row.window_trading_days} className="border-t border-slate-800">
                      <td className="py-1.5 text-slate-300">
                        {row.window_trading_days} trading day
                        {row.window_trading_days === 1 ? "" : "s"}
                      </td>
                      <td className="py-1.5 text-right tabular text-emerald-400">
                        {percent(row.correct / row.n)}
                      </td>
                      <td className="py-1.5 text-right tabular text-slate-600">{row.n}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
              <p className="mt-2 text-xs text-slate-500">
                Mean realised move {percent(kpi.backtest.mean_realized_pct / 100, 2)}.
              </p>
            </>
          )}
          <p className="mt-3 text-[11px] text-slate-600">
            Windows are counted in TRADING days: the Iranian gold market closes on Fridays
            and holidays, so a calendar window would score every weekend prediction as
            &ldquo;no movement&rdquo; and quietly flatter the model.{" "}
            {number(kpi.backtest.unscored_neutral)} prediction
            {kpi.backtest.unscored_neutral === 1 ? " is" : "s are"} unscored because the
            model said «خنثی» or «نامطمئن» — a non-prediction is excluded rather than counted
            as a free win.
          </p>
        </Card>
      </div>
    </>
  );
}
