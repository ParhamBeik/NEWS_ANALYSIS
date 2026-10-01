/**
 * Swipe-review input mapping, kept free of React so it can be tested directly.
 *
 * Directions are physical, not logical: right is "agree" in both Persian and English,
 * matching the gesture, the arrow key and the button placement.
 */

export const SWIPE_THRESHOLD = 80;

/** A finished drag becomes an action only when it is long and mostly horizontal. */
export function gestureAction(dx, dy = 0) {
  if (Math.abs(dx) < SWIPE_THRESHOLD || Math.abs(dx) <= Math.abs(dy)) return null;
  return dx > 0 ? "agree" : "fix";
}

export function keyAction({ key, ctrlKey = false, metaKey = false, altKey = false }) {
  if ((ctrlKey || metaKey) && !altKey && key?.toLowerCase() === "z") return "undo";
  if (ctrlKey || metaKey || altKey) return null;
  return { ArrowRight: "agree", ArrowLeft: "fix", ArrowDown: "skip" }[key] ?? null;
}
