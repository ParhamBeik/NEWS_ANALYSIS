"use server";

import { apiFetch } from "@/lib/api";

export async function saveAlertSubscription(subscription, interests) {
  const response = await apiFetch("/api/alerts/subscriptions/", {
    method: "POST", body: JSON.stringify({ subscription, ...interests }),
  });
  if (!response.ok) return { error: response.status === 401 ? "sign_in" : "subscribe_failed" };
  return { subscribed: true };
}

export async function removeAlertSubscription(endpoint) {
  const response = await apiFetch("/api/alerts/subscriptions/", {
    method: "DELETE", body: JSON.stringify({ endpoint }),
  });
  return { removed: response.ok };
}
