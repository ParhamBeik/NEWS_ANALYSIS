import Link from "next/link";
import ArticleCard from "@/components/ArticleCard";
import AsyncPanel, { Skeleton } from "@/components/AsyncPanel";
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
// 400 from django-filter. Backed by a test in api/tests/test_api.py.
const NOTIFY_STATES = [
  ["اطلاع‌رسانی شود", "Notify"],
  ["اطلاع‌رسانی نشود", "Quiet"],
  ["ارزیابی ناکافی", "Insufficient"],
];

/** A pagination href that never emits `/?&offset=20`. */
function pageHref(params, offset) {
  const search = new URLSearchParams();
  for (const [key, value] of Object.entries(params)) {
    if (key === "offset" || value === undefined || value === null || value === "") continue;
    search.set(key, Array.isArray(value) ? value[0] : value);
  }
  if (offset > 0) search.set("offset", String(offset));
  const encoded = search.toString();
  return encoded ? `/?${encoded}` : "/";
}

/**
 * The four header numbers, on their own.
 *
 * `/api/ops/` is the most expensive endpoint in the app - roughly fifteen aggregates, one
 * of which walks the latest evaluation of every article ever stored. Awaiting it before
 * showing the feed meant the primary page paid the dashboard's cost on every load, to
 * print four integers.
 */
async function FeedMetrics() {
  const ops = await apiGet("/api/ops/?days=1");
  const notified = ops.notify?.["اطلاع‌رسانی شود"] ?? 0;
  const spend = ops.budget.spent_today_usd;
  return (
    <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
      <Metric label="Fetched (24h)" value={number(ops.funnel.fetched)} />
      <Metric label="Analysed (24h)" value={number(ops.funnel.evaluated)} />
      <Metric
        label="Flagged notify (24h)"
        value={number(notified)}
        tone={notified ? "text-emerald-400" : ""}
      />
      <Metric
        label="Spend today"
        value={money(spend)}
        hint={`ceiling ${money(ops.budget.daily_ceiling_usd, 2)}`}
        tone={spend > ops.budget.daily_ceiling_usd * 0.8 ? "text-amber-400" : ""}
      />
    </div>
  );
}

/**
 * The filter bar reads `/api/sources/`, not `/api/ops/`.
 *
 * It only ever needed a name and a display name. Taking them off the ops aggregate coupled
 * the ability to FILTER the feed to the health of the dashboard - so a slow or broken /ops
 * removed the controls as well as the counters.
 */
async function Filters({ params }) {
  const sources = await apiGet("/api/sources/");
  return (
    <FeedFilters
      sources={sources.results}
      categories={CATEGORIES}
      notifyStates={NOTIFY_STATES}
      current={params}
    />
  );
}

async function FeedList({ params, offset }) {
  const feed = await apiGet(
    `/api/articles/${query({
      limit: PAGE_SIZE,
      offset: offset || undefined,
      source: params.source,
      category: params.category,
      notify: params.notify,
      q: params.q,
      unanalysed: params.unanalysed,
      include_duplicates: params.include_duplicates,
    })}`,
  );

  return (
    <>
      <p className="mb-3 text-sm text-slate-500">
        {number(feed.count)} stories match. Persian content, English chrome.
      </p>

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
            href={pageHref(params, Math.max(0, offset - PAGE_SIZE))}
            className="text-emerald-400 hover:underline"
          >
            ← Newer
          </Link>
        ) : (
          <span />
        )}
        <span className="text-xs text-slate-600 tabular">
          {feed.count
            ? `${offset + 1}–${Math.min(offset + PAGE_SIZE, feed.count)} of ${feed.count}`
            : ""}
        </span>
        {feed.next ? (
          <Link
            href={pageHref(params, offset + PAGE_SIZE)}
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

export default async function FeedPage({ searchParams }) {
  const params = (await searchParams) || {};
  const offset = Number(params.offset || 0);

  // Three independent regions, three boundaries. They start fetching together - siblings
  // suspend in parallel - so this is no slower than the old Promise.all, but the heading
  // and whichever region answers first paint immediately instead of waiting for the rest,
  // and a failure is contained to the panel that failed.
  return (
    <>
      <div className="mb-6">
        <h1 className="text-2xl font-semibold text-slate-100">Analyst feed</h1>
      </div>

      <div className="mb-6">
        <AsyncPanel label="24-hour metrics" fallback={<MetricsSkeleton />}>
          <FeedMetrics />
        </AsyncPanel>
      </div>

      <AsyncPanel label="Filters" fallback={<Skeleton className="mb-5 h-11 w-full" />}>
        <Filters params={params} />
      </AsyncPanel>

      <AsyncPanel label="Feed" fallback={<FeedSkeleton />}>
        <FeedList params={params} offset={offset} />
      </AsyncPanel>
    </>
  );
}

function MetricsSkeleton() {
  return (
    <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
      {[0, 1, 2, 3].map((index) => (
        <Skeleton key={index} className="h-[86px]" />
      ))}
    </div>
  );
}

function FeedSkeleton() {
  return (
    <div className="grid gap-3">
      {[0, 1, 2, 3, 4].map((index) => (
        <Skeleton key={index} className="h-24" />
      ))}
    </div>
  );
}
