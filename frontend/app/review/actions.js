"use server";

import { apiGet, apiPost } from "@/lib/api";

export async function submitLabel(caseId, payload) {
  await apiPost(`/api/reviews/${caseId}/submit/`, payload);
  return apiGet("/api/reviews/next/");
}

export async function skipCase(caseId, notes) {
  await apiPost(`/api/reviews/${caseId}/skip/`, { reviewer_notes: notes });
  return apiGet("/api/reviews/next/");
}
