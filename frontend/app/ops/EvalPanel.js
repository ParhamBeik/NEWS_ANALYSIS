import { Card, SectionTitle, StackedTable } from "@/components/primitives";
import { apiGet } from "@/lib/api";
import { money, number, percent, tehranTime } from "@/lib/display";

/**
 * Staff-only release gate on /ops, fed by /api/ops/evals/: the latest `shadow_eval` runs of
 * the decision backend against staff-labelled items. One row per backend/model, because
 * GapGPT fallback confidences are not calibrated and never compare with TypeSafe's.
 */

const VERDICT_TONE = {
  pass: "text-emerald-400",
  fail: "text-rose-400",
  insufficient_labels: "text-amber-400",
  aborted: "text-amber-400",
};

const rate = (value) => (value == null ? "—" : percent(value, 0));

export default async function EvalPanel({ tr }) {
  const data = await apiGet("/api/ops/evals/").catch(() => null);
  if (!data) return null;
  return (
    <Card className="p-4 lg:col-span-2">
      <SectionTitle hint={tr("shadow eval vs staff labels; re-run on any prompt or model change", "ارزیابی سایه در برابر برچسب‌های کارشناسان")}>
        {tr("Classifier release gate", "دروازه انتشار طبقه‌بند")}
      </SectionTitle>
      {data.runs.length === 0 ? (
        <p className="text-sm text-slate-500">
          {tr("No eval runs yet. Run manage.py shadow_eval.", "هنوز ارزیابی اجرا نشده است.")}
        </p>
      ) : (
        <StackedTable
          rowKey={(row) => String(row.id)}
          rows={data.runs}
          columns={[
            { key: "created_at", label: tr("When", "زمان"), className: "whitespace-nowrap text-xs text-slate-500", render: (row) => tehranTime(row.created_at) },
            { key: "model", label: tr("Backend / model", "مدل"), className: "text-xs text-slate-300", render: (row) => `${row.backend} · ${row.model} · ${row.language}` },
            {
              key: "verdict", label: tr("Verdict", "نتیجه"), className: "text-xs",
              render: (row) => (
                <span className={VERDICT_TONE[row.verdict] || "text-slate-400"} title={row.reasons.join("; ")}>
                  {row.verdict}
                </span>
              ),
            },
            { key: "labelled", label: tr("Labels", "برچسب"), end: true, render: (row) => `${number(row.labelled)} + ${number(row.grouping_pairs)}` },
            { key: "topic", label: tr("Topic", "موضوع"), end: true, render: (row) => rate(row.metrics.overall?.topic_accuracy) },
            { key: "iran", label: tr("Iran ±1", "ایران ±۱"), end: true, render: (row) => rate(row.metrics.overall?.iran_tier_within_one) },
            { key: "global", label: tr("Global ±1", "جهانی ±۱"), end: true, render: (row) => rate(row.metrics.overall?.global_tier_within_one) },
            { key: "grouping", label: tr("Grouping P/R", "گروه‌بندی"), end: true, render: (row) => `${rate(row.metrics.grouping?.precision)} / ${rate(row.metrics.grouping?.recall)}` },
            { key: "cost", label: tr("Cost", "هزینه"), end: true, render: (row) => money(Number(row.cost_usd)) },
          ]}
        />
      )}
    </Card>
  );
}
