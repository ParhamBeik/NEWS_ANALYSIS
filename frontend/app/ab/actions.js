"use server";

import { revalidatePath } from "next/cache";
import { apiGet, apiPost } from "@/lib/api";

/**
 * Server actions for the A/B tab.
 *
 * The judgement round-trips through the server so the token never reaches the browser -
 * and, more importantly here, so the client never receives anything that could identify
 * the arms. A client-side fetch would have to be given a token that can read
 * `/api/variants/`, which is exactly the unblinding this design prevents.
 */

export async function nextPair() {
  return apiGet("/api/ab/pairs/next/");
}

export async function submitJudgement(pairId, winner, reasoning) {
  const revealed = await apiPost(`/api/ab/pairs/${pairId}/feedback/`, { winner, reasoning });
  revalidatePath("/ab");
  const next = await apiGet("/api/ab/pairs/next/");
  return { revealed, next };
}

export async function standings() {
  return apiGet("/api/ab/pairs/results/");
}
