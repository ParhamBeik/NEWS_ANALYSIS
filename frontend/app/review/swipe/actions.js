"use server";

import { apiGet, apiPost, query } from "@/lib/api";

// Django is the authorization boundary: every call carries the staff token server-side.

export async function decide(eventId, payload) {
  return apiPost(`/api/review/events/${Number(eventId)}/`, payload);
}

export async function splitArticle(eventId, articleId) {
  return apiPost(`/api/review/events/${Number(eventId)}/split/`, { article_id: Number(articleId) });
}

export async function sessionStats(since) {
  return apiGet(`/api/review/stats/${query({ since })}`);
}
