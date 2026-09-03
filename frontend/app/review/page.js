import { apiGet } from "@/lib/api";
import ReviewForm from "./ReviewForm";

export const metadata = { title: "Review · News Intelligence" };
export const dynamic = "force-dynamic";

export default async function ReviewPage() {
  const initialCase = await apiGet("/api/reviews/next/");
  return (
    <>
      <h1 className="mb-1 text-2xl font-semibold text-slate-100">Review queue</h1>
      <p className="mb-5 text-sm text-slate-500">
        Ground truth, not preference. What you approve here is what the model is measured
        against on the Quality page and what the retrieval memory feeds back as an example —
        so an axis you cannot judge belongs on &ldquo;not assessed&rdquo;, never on a level.
      </p>
      <ReviewForm initialCase={initialCase} />
    </>
  );
}
