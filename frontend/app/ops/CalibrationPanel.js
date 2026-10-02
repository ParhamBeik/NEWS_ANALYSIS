import { Card, Metric, SectionTitle, StackedTable } from "@/components/primitives";
import { apiGet } from "@/lib/api";
import { number, percent, tehranTime } from "@/lib/display";

/**
 * Staff-only calibration signal on /ops, fed by /api/ops/calibration/: per impact tier and
 * asset class, how unusual the market move after an event was (mean |z| against the asset's
 * trailing 30 days) and how often it cleared |z| >= 1. Higher tiers should show both rising.
 */

const z = (value) => (value == null ? "—" : value.toFixed(2));

function Table({ rows, keyLabel, renderKey, tr }) {
  return (
    <StackedTable
      rowKey={(row) => String(row.key)}
      rows={rows}
      columns={[
        { key: "key", label: keyLabel, render: renderKey },
        { key: "reactions", label: tr("Reactions", "واکنش"), end: true, render: (row) => number(row.reactions) },
        { key: "mean_abs_z", label: tr("Mean |z|", "میانگین |z|"), end: true, render: (row) => z(row.mean_abs_z) },
        { key: "hit_rate", label: tr("|z| ≥ 1", "|z| ≥ ۱"), end: true, render: (row) => (row.hit_rate == null ? "—" : percent(row.hit_rate, 0)) },
      ]}
    />
  );
}

export default async function CalibrationPanel({ tr }) {
  const data = await apiGet("/api/ops/calibration/").catch(() => null);
  if (!data) return null;
  const last = data.last_run;
  const feedDown = !data.configured || last?.status === "unavailable";
  return (
    <Card className="p-4">
      <SectionTitle hint={tr(`event reactions, last ${data.window_days} days`, `واکنش بازار به رویدادها، ${data.window_days} روز گذشته`)}>
        {tr("Market calibration", "کالیبراسیون بازار")}
      </SectionTitle>
      <div className="mb-4 grid grid-cols-2 gap-3">
        <Metric label={tr("Price feed", "منبع قیمت")}
          value={feedDown ? tr("not connected", "متصل نیست") : tr("Portfolio", "پورتفولیو")}
          tone={feedDown ? "text-amber-400" : "text-emerald-400"}
          hint={last?.at ? `${tr("last run", "آخرین اجرا")} ${tehranTime(last.at)}` : null} />
        <Metric label={tr("Skipped runs", "اجرای ردشده")} value={number(data.unavailable_runs)}
          tone={data.unavailable_runs ? "text-amber-400" : ""}
          hint={last?.reason || null} />
      </div>
      {data.by_tier.length === 0 ? (
        <p className="text-sm text-slate-500">{tr("No reactions measured yet.", "هنوز واکنشی اندازه‌گیری نشده است.")}</p>
      ) : (
        <div className="space-y-4">
          <Table rows={data.by_tier} tr={tr} keyLabel={tr("Tier", "سطح")} renderKey={(row) => number(row.key)} />
          <Table rows={data.by_asset_class} tr={tr} keyLabel={tr("Asset class", "دسته دارایی")} />
        </div>
      )}
    </Card>
  );
}
