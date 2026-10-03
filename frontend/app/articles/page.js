import Link from "next/link";
import ArticleCard from "@/components/ArticleCard";
import AsyncPanel, { Skeleton } from "@/components/AsyncPanel";
import FeedFilters from "@/components/FeedFilters";
import { EmptyState, QueryError } from "@/components/primitives";
import { ApiError, apiGet, query } from "@/lib/api";
import { number } from "@/lib/display";
import { language, label } from "@/lib/language";
import { staffDenied } from "@/components/StaffGate";

export const metadata = { title: "Articles · News Intelligence" };
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
  return encoded ? `/articles?${encoded}` : "/articles";
}

/**
 * The filter bar reads `/api/sources/`, not `/api/ops/`.
 *
 * It only ever needed a name and a display name. Taking them off the ops aggregate coupled
 * the ability to FILTER the feed to the health of the dashboard - so a slow or broken /ops
 * removed the controls as well as the counters.
 */
async function Filters({ params, lang }) {
  const sources = await apiGet("/api/sources/");
  return (
    <FeedFilters
      sources={sources.results}
      categories={CATEGORIES}
      notifyStates={NOTIFY_STATES}
      current={params}
      lang={lang}
    />
  );
}

async function FeedList({ params, offset, lang }) {
  const tr = (en, fa) => label(lang, en, fa);
  let feed;
  try {
    feed = await apiGet(
      `/api/articles/${query({
        limit: PAGE_SIZE,
        offset: offset || undefined,
        source: params.source,
        category: params.category,
        notify: params.notify,
        q: params.q,
        unanalysed: params.unanalysed,
        include_duplicates: params.include_duplicates,
        stored_day: params.stored_day,
        classified: params.classified,
        evaluated: params.evaluated,
        order: params.order,
      })}`,
    );
  } catch (error) {
    if (error instanceof ApiError && error.status === 400) {
      return (
        <QueryError title="Invalid feed filter.">
          Clear the invalid filter and try again.
        </QueryError>
      );
    }
    throw error;
  }

  return (
    <>
      <p className="mb-3 text-sm text-slate-500">
        {number(feed.count)} {tr("articles match.", "مقاله یافت شد.")}
      </p>

      {feed.results.length === 0 ? (
        <EmptyState title={tr("No articles match these filters.", "مقاله‌ای با این فیلترها یافت نشد.")}>
          {tr("Try clearing a filter.", "فیلترها را پاک کنید.")}
        </EmptyState>
      ) : (
        <div className="grid gap-3">
          {feed.results.map((article) => (
            <ArticleCard key={article.id} article={article} />
          ))}
        </div>
      )}

      <div className="mt-6 flex items-center justify-between gap-2 text-sm">
        {offset > 0 ? (
          <Link
            href={pageHref(params, Math.max(0, offset - PAGE_SIZE))}
            className="text-emerald-400 hover:underline"
          >
            {tr("← Newer", "جدیدتر →")}
          </Link>
        ) : (
          <span />
        )}
        <span className="text-center text-xs text-slate-600 tabular">
          {feed.count
            ? `${offset + 1}–${Math.min(offset + PAGE_SIZE, feed.count)} of ${feed.count}`
            : ""}
        </span>
        {feed.next ? (
          <Link
            href={pageHref(params, offset + PAGE_SIZE)}
            className="text-emerald-400 hover:underline"
          >
            {tr("Older →", "← قدیمی‌تر")}
          </Link>
        ) : (
          <span />
        )}
      </div>
    </>
  );
}

export default async function FeedPage({ searchParams }) {
  const denied = await staffDenied();
  if (denied) return denied;
  const params = (await searchParams) || {};
  const offset = Number(params.offset || 0);
  const lang = await language();
  const tr = (en, fa) => label(lang, en, fa);
  const activeStage = params.classified === "true" ? "Classified" : params.classified === "false"
    ? "Unclassified" : params.evaluated === "true" ? "Evaluated"
    : params.evaluated === "false" ? "Unevaluated" : null;

  return (
    <>
      <div className="mb-6">
        <h1 className="text-2xl font-semibold text-slate-100">{tr("Articles", "مقالات")}</h1>
        {(params.stored_day || activeStage) && <p className="mt-2 text-sm text-slate-400">
          {params.stored_day && `${tr("Stored on", "ذخیره‌شده در")} ${params.stored_day} · `}{activeStage || tr("All stages", "همه مراحل")}
          {" · "}<Link href="/articles" className="text-emerald-300 hover:underline">{tr("Clear filters", "پاک کردن فیلترها")}</Link>
        </p>}
      </div>
      <AsyncPanel label="Filters" fallback={<Skeleton className="mb-5 h-11 w-full" />}>
        <Filters params={params} lang={lang} />
      </AsyncPanel>

      <AsyncPanel label="Feed" fallback={<FeedSkeleton />}>
        <FeedList params={params} offset={offset} lang={lang} />
      </AsyncPanel>
    </>
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
