"use server";

import { apiPost } from "@/lib/api";

// Django is the authorization boundary: only staff tokens pass IsAdminUser.

export async function setEventHidden(eventId, hidden, reason) {
  return apiPost(`/api/staff/events/${Number(eventId)}/visibility/`, { action: hidden ? "hide" : "unhide", reason });
}

export async function setArticleHidden(articleId, hidden, reason) {
  return apiPost(`/api/staff/articles/${Number(articleId)}/visibility/`, { action: hidden ? "hide" : "unhide", reason });
}
