import Link from "next/link";
import ArticleCard from "@/components/ArticleCard";
import FeedFilters from "@/components/FeedFilters";
import { EmptyState, Metric } from "@/components/primitives";
import { apiGet, query } from "@/lib/api";
import { money, number } from "@/lib/display";

export const metadata = { title: "Feed · News Intelligence" };
export const dynamic = "force-dynamic";

const PAGE_SIZE = 20;

const CATEGORIES = [
  ["security", "Security"],
  ["economics", "Economics"],
  ["security/economics", "Security + Economics"],
  ["other", "Other"],
];

// The VALUES here are `core.vocabulary.NotifyStatus`, character for character. `notify` is
// a ChoiceFilter, so a near-miss is not a filter that quietly matches nothing - it is a
// 400 from django-filter, and the feed page renders its error boundary instead.
const NOTIFY_STATES = [
  ["اطلاع‌رسانی شود", "Notify"],
  ["اطلاع‌رسانی نشود", "Quiet"],
  ["ارزیابی ناکافی", "Insufficient"],
];

export default async function FeedPage({ searchParams }) {
  const params = await searchParams;
  const offset = Number(params?.offset || 0);

  // Two requests in parallel, not four sequential ones: the header counters and the feed
  // are independent, and awaiting them in series doubles the page's time to first byte.
  const [feed, ops] = await Promise.all([
    apiGet(
      `/api/articles/${query({
        limit: PAGE_SIZE,
        offset: offset || undefined,
        source: params?.source,
        category: params?.category,
        notify: params?.notify,
        q: params?.q,
        unanalysed: params?.unanalysed,
        include_duplicates: params?.include_duplicates,
      })}`,
    ),
    apiGet("/api/ops/?days=1"),
  ]);

  const notified = ops.notify?.["اطلاع‌رسانی شود"] ?? 0;
  const pageParams = new URLSearchParams(
    Object.entries(params || {}).filter(([key]) => key !== "offset"),
  );

  return (
    <>
      <div className="mb-6 flex flex-wrap items-end justify-between gap-4">
        <div>
          <h1 className="text-2xl font-semibold text-slate-100">Analyst feed</h1>
          <p className="mt-1 text-sm text-slate-500">
            {number(feed.count)} stories match. Persian content, English chrome.
          </p>
        </div>
      </div>

      <div className="mb-6 grid grid-cols-2 gap-3 sm:grid-cols-4">
        <Metric label="Fetched (24h)" value={number(ops.funnel.fetched)} />
        <Metric label="Analysed (24h)" value={number(ops.funnel.evaluated)} />
        <Metric
          label="Flagged notify"
          value={number(notified)}
          tone={notified ? "text-emerald-400" : ""}
        />
        <Metric
          label="Spend today"
          value={money(ops.budget.spent_today_usd)}
          hint={`ceiling ${money(ops.budget.daily_ceiling_usd, 2)}`}
          tone={
            ops.budget.spent_today_usd > ops.budget.daily_ceiling_usd * 0.8
              ? "text-amber-400"
              : ""
          }
        />
      </div>

      <FeedFilters
        sources={ops.sources}
        categories={CATEGORIES}
        notifyStates={NOTIFY_STATES}
        current={params || {}}
      />

      {feed.results.length === 0 ? (
        <EmptyState title="No stories match these filters.">
          Try clearing the search box, or widen the verdict filter.
        </EmptyState>
      ) : (
        <div className="grid gap-3">
          {feed.results.map((article) => (
            <ArticleCard key={article.id} article={article} />
          ))}
        </div>
      )}

      <div className="mt-6 flex items-center justify-between text-sm">
        {offset > 0 ? (
          <Link
            href={`/?${pageParams}&offset=${Math.max(0, offset - PAGE_SIZE)}`}
            className="text-emerald-400 hover:underline"
          >
            ← Newer
          </Link>
        ) : (
          <span />
        )}
        <span className="text-xs text-slate-600 tabular">
          {feed.count ? `${offset + 1}–${Math.min(offset + PAGE_SIZE, feed.count)} of ${feed.count}` : ""}
        </span>
        {feed.next ? (
          <Link
            href={`/?${pageParams}&offset=${offset + PAGE_SIZE}`}
            className="text-emerald-400 hover:underline"
          >
            Older →
          </Link>
        ) : (
          <span />
        )}
      </div>
    </>
  );
}
