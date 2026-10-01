"use client";

import Link from "next/link";
import { useEffect, useRef, useState } from "react";

const COLORS = {
  monetary: "#60a5fa", macro: "#a78bfa", sanctions_trade: "#f97316",
  geopolitics: "#ef4444", energy: "#eab308", markets: "#34d399",
};
const RANGE_DAYS = { "1W": 7, "1M": 30, "3M": 90, "1Y": 365 };

export default function AssetTimeline({ data, lang }) {
  const container = useRef(null);
  const [selected, setSelected] = useState(null);
  const persian = lang === "fa";
  const eventTitle = (event) => persian ? event.title : (event.title_en || event.original_title || event.title);

  useEffect(() => {
    let chart;
    let observer;
    let cancelled = false;
    import("echarts").then((echarts) => {
      if (cancelled || !container.current) return;
      chart = echarts.init(container.current, null, { renderer: "canvas" });
      const markers = data.events.map((row, index) => ({
        value: [row.event.event_time, 0.35 + (index % 3) * 0.22, row.relevance || 0],
        eventId: row.event.id,
        itemStyle: { color: COLORS[row.event.category] || "#94a3b8" },
      }));
      const end = new Date(data.as_of).getTime();
      const start = end - RANGE_DAYS[data.range] * 24 * 60 * 60 * 1000;
      chart.setOption({
        backgroundColor: "transparent",
        animation: false,
        aria: { show: true, description: persian ? "نمودار قیمت و رویدادها در یک محور زمان" : "Price chart and news events on a shared time axis" },
        tooltip: { trigger: "item", formatter: (point) => point.seriesName === "Events"
          ? eventTitle(data.events.find((row) => row.event.id === point.data.eventId)?.event || {})
          : `${new Date(point.value[0]).toLocaleString()} · ${point.value[1]}` },
        grid: [
          { left: 75, right: 20, top: 20, height: "62%" },
          { left: 75, right: 20, top: "72%", height: "12%" },
        ],
        xAxis: [
          { type: "time", gridIndex: 0, min: start, max: end, axisLabel: { color: "#94a3b8" }, axisLine: { lineStyle: { color: "#475569" } } },
          { type: "time", gridIndex: 1, min: start, max: end, axisLabel: { color: "#94a3b8" }, axisLine: { lineStyle: { color: "#475569" } } },
        ],
        yAxis: [
          { type: "value", gridIndex: 0, scale: true, axisLabel: { color: "#94a3b8" }, splitLine: { lineStyle: { color: "#1e293b" } } },
          { type: "value", gridIndex: 1, min: 0, max: 1, show: false },
        ],
        dataZoom: [{ type: "inside", xAxisIndex: [0, 1] }, { type: "slider", xAxisIndex: [0, 1], bottom: 0, height: 20 }],
        series: [
          { name: "Price", type: "line", xAxisIndex: 0, yAxisIndex: 0, showSymbol: false,
            lineStyle: { color: "#34d399", width: 2 },
            data: data.points.map((point) => [point.observed_at, Number(point.price)]) },
          { name: "Events", type: "scatter", xAxisIndex: 1, yAxisIndex: 1,
            symbolSize: (value) => 10 + Math.min(100, value[2]) * 0.18, data: markers },
        ],
      });
      chart.on("click", (point) => {
        if (point.seriesName === "Events") setSelected(point.data.eventId);
      });
      observer = new ResizeObserver(() => chart.resize());
      observer.observe(container.current);
    });
    return () => { cancelled = true; observer?.disconnect(); chart?.dispose(); };
  }, [data, persian]);

  const active = data.events.find((row) => row.event.id === selected);
  return <div className="space-y-5">
    <div ref={container} role="img" aria-label={persian ? "نمودار قیمت با رویدادهای خبری" : "Price timeline with news event bubbles"} className="h-[420px] w-full" />
    <p className="text-xs text-slate-400">{persian ? "اندازهٔ دایره: ارتباط احتمالی با این دارایی؛ رنگ: موضوع خبر. نزدیکی زمانی، رابطهٔ علّی را ثابت نمی‌کند." : "Bubble size: potential asset relevance; color: news category. Timing alone does not establish causation."}</p>
    {active ? <div className="rounded-lg border border-emerald-800 bg-slate-900 p-4" aria-live="polite">
      <Link href={`/events/${active.event.id}`} className="font-semibold text-emerald-300" dir="auto">{eventTitle(active.event)}</Link>
      <p className="mt-1 text-sm text-slate-400">{new Date(active.event.event_time).toLocaleString()} · {active.relevance ?? "—"}/100</p>
      {Object.entries(active.observed_changes).map(([window, result]) => <p key={window} className="mt-2 text-sm">
        {window}: {result.percent}% · {persian ? "تغییر مشاهده‌شده، نه اثر اثبات‌شده" : result.label}
      </p>)}
    </div> : null}
    <section><h2 className="mb-3 text-lg font-semibold">{persian ? "فهرست رویدادها" : "Events on this chart"}</h2>
      <div className="grid gap-2">{data.events.map((row) => <button key={row.event.id} type="button" onClick={() => setSelected(row.event.id)}
        className="rounded-lg border border-slate-800 bg-slate-900 p-3 text-start hover:border-emerald-700 focus-visible:outline-2 focus-visible:outline-emerald-400">
        <span className="me-2 inline-block h-3 w-3 rounded-full" style={{ backgroundColor: COLORS[row.event.category] || "#94a3b8" }} aria-hidden="true" />
        <span dir="auto">{eventTitle(row.event)}</span>
        <span className="ms-2 text-xs text-slate-400">{new Date(row.event.event_time).toLocaleString()} · {row.relevance ?? "—"}/100</span>
      </button>)}</div>
    </section>
  </div>;
}
