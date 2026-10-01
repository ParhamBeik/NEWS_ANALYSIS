import { EmptyState } from "@/components/primitives";
import { apiGet, currentStaffUser } from "@/lib/api";
import { language } from "@/lib/language";
import SwipeReview from "./SwipeReview";

export const metadata = { title: "Swipe review · News Intelligence" };
export const dynamic = "force-dynamic";

export default async function SwipeReviewPage() {
  const lang = await language();
  if (!(await currentStaffUser())) {
    return (
      <EmptyState title={lang === "fa" ? "فقط برای کارکنان" : "Staff access required"}>
        {lang === "fa"
          ? "برچسب‌های بازبینی معیار سنجش مدل هستند و فقط کارکنان می‌توانند آن‌ها را ثبت کنند."
          : "Review labels are how the model is measured and are reserved for staff reviewers."}
      </EmptyState>
    );
  }
  const queue = await apiGet("/api/review/queue/?limit=25");
  return <SwipeReview initialCards={queue.results} pending={queue.pending} lang={lang} />;
}
