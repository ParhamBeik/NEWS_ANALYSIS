/**
 * Swipe-review mapping, the same rule as frontend/lib/swipe.js. Directions are physical:
 * right is "agree" in Persian and English alike.
 */
export const SWIPE_THRESHOLD = 80;

export function gestureAction(dx: number, dy = 0): "agree" | "fix" | null {
  if (Math.abs(dx) < SWIPE_THRESHOLD || Math.abs(dx) <= Math.abs(dy)) return null;
  return dx > 0 ? "agree" : "fix";
}

/** Review tiers are indexes 0-4 (core.review.LEVELS), not the reader's 1-5. */
export const REVIEW_TIERS = [
  { en: "Very low", fa: "خیلی کم" },
  { en: "Low", fa: "کم" },
  { en: "Medium", fa: "متوسط" },
  { en: "High", fa: "زیاد" },
  { en: "Very high", fa: "خیلی زیاد" },
];
