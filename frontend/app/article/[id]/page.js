import Link from "next/link";
import {
  Card,
  CategoryBadge,
  NotifyBadge,
  ScoreChip,
  SectionTitle,
  TrendBadge,
} from "@/components/primitives";
import { apiGet } from "@/lib/api";
import { AXIS_LABEL, tehranTime } from "@/lib/display";

export const dynamic = "force-dynamic";

const AXES = ["confidence_occurrence", "gold_price_impact", "security_relevance"];

export async function generateMetadata({ params }) {
  const { id } = await params;
  try {
    const article = await apiGet(`/api/articles/${id}/`);
    return { title: `${article.title} · News Intelligence` };
  } catch {
    return { title: "Article · News Intelligence" };
  }
}

function Provenance({ row }) {
  if (!row) return null;
  return (
    <p className="mt-3 border-t border-slate-800 pt-2 text-[11px] text-slate-600">
      {row.provider}:{row.model} · prompt {row.prompt_version} · {tehranTime(row.created_at)}
    </p>
  );
}

export default async function ArticlePage({ params }) {
  const { id } = await params;
  // The neighbours are a best-effort extra: an article with no embedding yet is normal,
  // and letting that 500 the whole detail page would be absurd.
  const [article, similar] = await Promise.all([
    apiGet(`/api/articles/${id}/`),
    apiGet(`/api/articles/${id}/similar/`).catch(() => []),
  ]);

  return (
    <div className="grid gap-6 lg:grid-cols-[1fr_360px]">
      <div>
        <Link href="/" className="text-xs text-slate-500 hover:text-slate-300">
          ← Back to feed
        </Link>

        <div className="mt-3 flex flex-wrap items-center gap-2 text-xs text-slate-500">
          <span className="rounded bg-slate-800 px-1.5 py-0.5 text-slate-300">
            {article.source}
          </span>
          {article.outlet && <bdi className="persian text-slate-400">{article.outlet}</bdi>}
          <span className="tabular">
            {article.published_at_jalali} {article.published_time}
          </span>
          <a
            href={article.url}
            target="_blank"
            rel="noreferrer noopener"
            className="text-emerald-500 hover:underline"
          >
            original ↗
          </a>
        </div>

        <h1 dir="rtl" className="persian mt-3 text-2xl font-semibold text-slate-50">
          {article.title}
        </h1>
        {article.title !== article.original_title && (
          <p dir="rtl" className="persian mt-1 text-sm text-slate-500">
            original headline: {article.original_title}
          </p>
        )}

        {(article.image?.file || article.image?.thumbnail) && (
          <img
            src={article.image.file || article.image.thumbnail}
            alt=""
            className="mt-4 w-full rounded-xl border border-slate-800 object-cover"
          />
        )}

        {article.summary?.one_line && (
          <Card className="mt-4 border-emerald-900/60 bg-emerald-950/20 p-4">
            <SectionTitle>Analyst one-liner</SectionTitle>
            <p dir="rtl" className="persian text-slate-100">
              {article.summary.one_line}
            </p>
          </Card>
        )}

        {article.lead && (
          <p dir="rtl" className="persian mt-4 text-slate-300">
            {article.lead}
          </p>
        )}
        {article.content && (
          <div dir="rtl" className="persian mt-4 whitespace-pre-wrap text-slate-400">
            {article.content}
          </div>
        )}
        {!article.content && (
          <p className="mt-4 text-sm text-amber-500/80">
            Only the feed summary was retrievable for this story (extraction tier:{" "}
            {article.extraction_tier}). The outlet gates its article pages, so the model
            reasoned from the headline and lead alone.
          </p>
        )}

        {article.duplicates?.length > 0 && (
          <div className="mt-6">
            <SectionTitle hint="collapsed by trigram similarity ≥ 0.75">
              Other copies of this story
            </SectionTitle>
            <div className="grid gap-2">
              {article.duplicates.map((duplicate) => (
                <Card key={duplicate.id} className="flex items-center gap-3 p-3 text-sm">
                  <span className="rounded bg-slate-800 px-1.5 py-0.5 text-xs text-slate-300">
                    {duplicate.source}
                  </span>
                  <bdi dir="rtl" className="persian flex-1 text-slate-400">
                    {duplicate.title}
                  </bdi>
                  <span className="tabular text-xs text-slate-600">
                    {duplicate.score?.toFixed(3)}
                  </span>
                </Card>
              ))}
            </div>
          </div>
        )}
      </div>

      {/* Everything the model decided, and why. This column is the point of the page: a
          verdict without its reasoning is a number a reviewer can only accept or reject,
          not argue with. */}
      <aside className="space-y-4">
        <Card className="p-4">
          <SectionTitle>Verdict</SectionTitle>
          {article.evaluation ? (
            <>
              <div className="mb-3 flex flex-wrap items-center gap-2">
                <CategoryBadge category={article.category} />
                <TrendBadge trend={article.evaluation.gold_trend} />
              </div>
              <NotifyBadge decision={article.evaluation.decision} showReason />
              <div className="mt-3 space-y-1.5">
                {AXES.map((axis) => (
                  <ScoreChip key={axis} axis={axis} score={article.evaluation.scores[axis]} />
                ))}
              </div>
              <p className="mt-3 text-xs text-slate-500">
                {article.evaluation.decision.axes_assessed} of 3 axes assessed,{" "}
                {article.evaluation.decision.strong_axes} strong.
              </p>
              {article.evaluation.rationale && (
                <p dir="rtl" className="persian mt-3 text-sm text-slate-300">
                  {article.evaluation.rationale}
                </p>
              )}
              <Provenance row={article.evaluation} />
            </>
          ) : (
            <p className="text-sm text-slate-500">
              {article.prefilter_reason
                ? `Skipped before inference: ${article.prefilter_reason}. The article is stored and can be re-queued.`
                : "Not yet evaluated."}
            </p>
          )}
        </Card>

        {article.classification && (
          <Card className="p-4">
            <SectionTitle>Classification</SectionTitle>
            <div className="flex items-center gap-2">
              <CategoryBadge category={article.classification.category} />
              {article.classification.confidence && (
                <span className="text-xs text-slate-500">
                  confidence <bdi className="persian">{article.classification.confidence}</bdi>
                </span>
              )}
            </div>
            {article.classification.matched_keywords?.length > 0 && (
              <div className="mt-2 flex flex-wrap gap-1">
                {article.classification.matched_keywords.map((word) => (
                  <span
                    key={word}
                    className="persian rounded bg-slate-800 px-1.5 py-0.5 text-xs text-slate-300"
                  >
                    <bdi>{word}</bdi>
                  </span>
                ))}
              </div>
            )}
            {article.classification.rationale && (
              <p dir="rtl" className="persian mt-2 text-sm text-slate-400">
                {article.classification.rationale}
              </p>
            )}
            <Provenance row={article.classification} />
          </Card>
        )}

        {/* The memory the model actually received, not a plausible reconstruction. */}
        {similar?.length > 0 && (
          <Card className="p-4">
            <SectionTitle hint="what the model was shown">Retrieved context</SectionTitle>
            <div className="space-y-2">
              {similar.map((item, index) => (
                <div key={index} className="rounded-lg border border-slate-800 p-2">
                  <div className="flex items-center justify-between gap-2 text-[11px]">
                    <span
                      className={
                        item.reviewed ? "text-emerald-400" : "text-amber-500"
                      }
                      title={
                        item.reviewed
                          ? "A human approved this label"
                          : "The model's own past verdict, fed back as context"
                      }
                    >
                      {item.reviewed ? "human-approved" : "model verdict"}
                    </span>
                    <span className="tabular text-slate-600">
                      {item.similarity?.toFixed(3)}
                    </span>
                  </div>
                  <bdi dir="rtl" className="persian mt-1 block text-xs text-slate-400">
                    {item.title}
                  </bdi>
                </div>
              ))}
            </div>
          </Card>
        )}

        <Card className="p-4 text-xs text-slate-500">
          <SectionTitle>Provenance</SectionTitle>
          <dl className="space-y-1">
            {[
              ["Fetched", tehranTime(article.fetched_at)],
              ["Extraction tier", article.extraction_tier],
              ["Native category", article.native_category || "—"],
              ["Content hash", article.content_hash?.slice(0, 12)],
              ["Quality flag", article.quality_flag || "clean"],
            ].map(([label, value]) => (
              <div key={label} className="flex justify-between gap-3">
                <dt>{label}</dt>
                <dd className="tabular text-slate-400">{value}</dd>
              </div>
            ))}
          </dl>
        </Card>
      </aside>
    </div>
  );
}
