import Link from "next/link";
import { AXIS_LABEL, LEVEL_STYLE, UNASSESSED_STYLE, levelIndex } from "@/lib/display";
import { CategoryBadge, NotifyBadge, TrendBadge } from "./primitives";

const AXES = ["confidence_occurrence", "gold_price_impact", "security_relevance"];

/**
 * One feed card.
 *
 * The image is served from OUR domain, not hot-linked from the Iranian outlet. It was
 * downloaded on the VPS during the crawl for exactly this reason: a Frankfurt browser
 * fetching from an Iranian CDN is the network error the whole page then has to explain.
 * If the download has not finished, the card shows a placeholder rather than a broken
 * image - `<img>` onError cannot be used in a server component and a dead icon on every
 * card looks like the site is broken.
 */
export default function ArticleCard({ article }) {
  const image = article.image?.thumbnail || article.image?.file;
  return (
    <article className="group grid grid-cols-1 gap-0 overflow-hidden rounded-xl border border-slate-800 bg-slate-900/50 transition hover:border-slate-700 sm:grid-cols-[200px_1fr]">
      <div className="relative hidden bg-slate-900 sm:block">
        {image ? (
          <img
            src={image}
            alt=""
            loading="lazy"
            className="h-full w-full object-cover"
          />
        ) : (
          <div className="flex h-full min-h-[150px] items-center justify-center text-[10px] uppercase tracking-widest text-slate-700">
            no image
          </div>
        )}
      </div>

      <div className="p-4">
        <div className="flex flex-wrap items-center gap-2 text-xs text-slate-500">
          <span className="rounded bg-slate-800 px-1.5 py-0.5 text-slate-300">
            {article.source}
          </span>
          {article.outlet && article.outlet !== article.source && (
            <bdi className="persian text-slate-400">{article.outlet}</bdi>
          )}
          <span className="tabular">
            {article.published_at_jalali || "undated"}
            {article.published_time ? ` ${article.published_time}` : ""}
          </span>
          {article.date_uncertain && (
            <span className="text-amber-500" title="Publication date could not be parsed">
              date uncertain
            </span>
          )}
          {/* The extraction tier is the early-warning signal for a site redesign, and it
              also explains a thin card: a "feed" tier article is ~220 chars of RSS because
              the outlet is Cloudflare-gated, not because the crawler failed. */}
          {article.extraction_tier && article.extraction_tier !== "jsonld" && (
            <span className="text-slate-600">tier: {article.extraction_tier}</span>
          )}
        </div>

        <Link href={`/article/${article.id}`} className="mt-2 block">
          <h3
            dir="rtl"
            className="persian text-lg font-semibold text-slate-100 group-hover:text-emerald-300"
          >
            {article.title}
          </h3>
        </Link>

        {article.lead && (
          <p dir="rtl" className="persian mt-1 line-clamp-2 text-sm text-slate-400">
            {article.lead}
          </p>
        )}

        <div className="mt-3 flex flex-wrap items-center gap-2">
          <CategoryBadge category={article.category} />
          <TrendBadge trend={article.scores?.gold_trend} />
          <NotifyBadge decision={article.decision} />
        </div>

        {article.scores ? (
          <div className="mt-3 flex flex-wrap gap-1.5">
            {AXES.map((axis) => {
              const score = article.scores[axis];
              const assessed = Boolean(score?.value);
              return (
                <span
                  key={axis}
                  title={`${AXIS_LABEL[axis]}: ${assessed ? score.label : "not assessed"}`}
                  className={`rounded border px-2 py-0.5 text-[11px] ${
                    assessed ? LEVEL_STYLE[score.value] : UNASSESSED_STYLE
                  }`}
                >
                  {AXIS_LABEL[axis].split(" ")[0]}{" "}
                  {assessed ? (
                    <span className="tabular">{levelIndex(score.value)}/5</span>
                  ) : (
                    "—"
                  )}
                </span>
              );
            })}
          </div>
        ) : (
          <p className="mt-3 text-xs text-slate-600">
            {article.prefilter_reason
              ? `skipped by prefilter: ${article.prefilter_reason}`
              : "awaiting analysis"}
          </p>
        )}
      </div>
    </article>
  );
}
