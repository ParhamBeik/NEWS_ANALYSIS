import Link from "next/link";
import { Card, EmptyState, Metric, SectionTitle } from "@/components/primitives";
import { apiGet } from "@/lib/api";
import { number, percent, tehranTime } from "@/lib/display";

export const metadata = { title: "Market · News Intelligence" };
export const dynamic = "force-dynamic";

/**
 * A dependency-free sparkline.
 *
 * A charting library would be ~150 KB of client JavaScript to draw one line, and would turn
 * this server component into a client one. An SVG polyline renders on the server and ships
 * nothing.
 */
function Sparkline({ points }) {
  if (points.length < 2) return null;
  const values = points.map((point) => Number(point.price));
  const min = Math.min(...values);
  const max = Math.max(...values);
  const span = max - min || 1;
  const path = values
    .map((value, index) => {
      const x = (index / (values.length - 1)) * 100;
      const y = 40 - ((value - min) / span) * 36;
      return `${x.toFixed(2)},${y.toFixed(2)}`;
    })
    .join(" ");
  const rising = values.at(-1) >= values[0];
  return (
    <svg viewBox="0 0 100 40" preserveAspectRatio="none" className="h-32 w-full">
      <polyline
        points={path}
        fill="none"
        strokeWidth="0.8"
        vectorEffect="non-scaling-stroke"
        className={rising ? "stroke-emerald-400" : "stroke-rose-400"}
      />
    </svg>
  );
}

export default async function MarketPage({ searchParams }) {
  const params = await searchParams;
  const symbol = params?.symbol || "gold_18k";
  const market = await apiGet(`/api/market/?symbol=${encodeURIComponent(symbol)}&days=30`);

  const series = market.series;
  const first = series[0] ?? null;
  const last = series.at(-1) ?? null;
  const change =
    first && last ? (Number(last.price) - Number(first.price)) / Number(first.price) : null;

  return (
    <>
      <div className="mb-5 flex flex-wrap items-end justify-between gap-3">
        <div>
          <h1 className="text-2xl font-semibold text-slate-100">Market</h1>
          <p className="mt-1 text-sm text-slate-500">
            TGJU series, polled every 15 minutes. This is the ground truth the gold-impact
            predictions are scored against.
          </p>
        </div>
        <div className="flex flex-wrap gap-1 text-xs">
          {market.symbols.map((option) => (
            <Link
              key={option.value}
              href={`/market?symbol=${option.value}`}
              className={`rounded-md px-2 py-1 ${
                option.value === market.symbol
                  ? "bg-slate-800 text-slate-100"
                  : "text-slate-500 hover:bg-slate-900"
              }`}
            >
              {option.label.split(" (")[0]}
            </Link>
          ))}
        </div>
      </div>

      {series.length === 0 ? (
        <EmptyState title="No prices recorded for this symbol yet.">
          The poller writes a snapshot every 15 minutes once the beat schedule is running.
        </EmptyState>
      ) : (
        <>
          <div className="mb-4 grid grid-cols-2 gap-3 md:grid-cols-4">
            <Metric
              label="Latest"
              value={number(market.latest?.price)}
              hint={tehranTime(market.latest?.observed_at)}
            />
            <Metric
              label="30-day change"
              value={percent(change, 2)}
              tone={change > 0 ? "text-emerald-400" : change < 0 ? "text-rose-400" : ""}
            />
            <Metric label="Snapshots" value={number(series.length)} />
            <Metric label="Scored predictions" value={number(market.outcomes.length)} />
          </div>

          <Card className="mb-6 p-4">
            <SectionTitle hint="Tehran local observation time">
              {market.symbols.find((option) => option.value === market.symbol)?.label}
            </SectionTitle>
            <Sparkline points={series} />
            <div className="mt-1 flex justify-between text-[11px] text-slate-600">
              <span>{tehranTime(first?.observed_at)}</span>
              <span>{tehranTime(last?.observed_at)}</span>
            </div>
          </Card>
        </>
      )}

      <Card className="p-4">
        <SectionTitle hint="one row per prediction, per window">
          Prediction outcomes
        </SectionTitle>
        {market.outcomes.length === 0 ? (
          <p className="text-sm text-slate-500">
            Nothing scored yet. An outcome needs a price on both ends of a trading-day
            window, and a directional prediction that was not «خنثی» or «نامطمئن».
          </p>
        ) : (
          <table className="w-full text-sm">
            <thead>
              <tr className="text-left text-[11px] uppercase tracking-wider text-slate-600">
                <th className="pb-1">Article</th>
                <th className="pb-1">Predicted</th>
                <th className="pb-1 text-right">Impact</th>
                <th className="pb-1 text-right">Window</th>
                <th className="pb-1 text-right">Realised</th>
                <th className="pb-1 text-right">Verdict</th>
              </tr>
            </thead>
            <tbody>
              {market.outcomes.map((row) => (
                <tr key={row.id} className="border-t border-slate-800">
                  <td className="py-1.5">
                    <Link
                      href={`/article/${row.article_id}`}
                      className="text-emerald-500 hover:underline"
                    >
                      #{row.article_id}
                    </Link>
                  </td>
                  <td className="persian py-1.5">
                    <bdi>{row.gold_trend || "—"}</bdi>
                  </td>
                  <td className="persian py-1.5 text-right text-slate-400">
                    <bdi>{row.gold_price_impact || "not assessed"}</bdi>
                  </td>
                  <td className="py-1.5 text-right tabular text-slate-500">
                    {row.window_trading_days}d
                  </td>
                  <td
                    className={`py-1.5 text-right tabular ${
                      row.realized_pct > 0 ? "text-emerald-400" : "text-rose-400"
                    }`}
                  >
                    {row.realized_pct?.toFixed(2)}%
                  </td>
                  <td className="py-1.5 text-right">
                    {row.direction_correct === null ? (
                      <span className="text-slate-600">not scored</span>
                    ) : row.direction_correct ? (
                      <span className="text-emerald-400">correct</span>
                    ) : (
                      <span className="text-rose-400">wrong</span>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </Card>
    </>
  );
}
