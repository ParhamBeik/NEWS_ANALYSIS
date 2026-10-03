import { EmptyState } from "@/components/primitives";
import { currentStaffUser } from "@/lib/api";
import { language } from "@/lib/language";

/**
 * One guard for every operator screen. Phone OTP lets anyone become a signed-in reader, and
 * the API answers those staff endpoints with 403 - so the page must say "staff only" in the
 * reader's language instead of crashing into the error boundary.
 *
 * Usage, first line of a staff page:  const denied = await staffDenied(); if (denied) return denied;
 */
export async function staffDenied() {
  if (await currentStaffUser()) return null;
  const lang = await language();
  return (
    <EmptyState title={lang === "fa" ? "فقط برای کارکنان" : "Staff access required"}>
      {lang === "fa"
        ? "این بخش ابزار داخلی تیم است. برای خواندن خبرها به رادار برگردید."
        : "This is an internal team tool. Head back to the news radar to read stories."}
    </EmptyState>
  );
}
