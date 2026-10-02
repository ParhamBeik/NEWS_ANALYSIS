"use server";

import { cookies } from "next/headers";
import { redirect } from "next/navigation";

import { apiFetch } from "@/lib/api";

const MIN_ITEMS = 3;

function message(lang, en, fa) {
  return lang === "en" ? en : fa;
}

async function send(path, method, body) {
  const response = await apiFetch(path, { method, body: JSON.stringify(body) });
  if (response.status === 401) redirect("/login");
  return response;
}

/** Watchlist and alert dial from a chips form; `onboarded` finishes onboarding. */
async function saveAccount(formData, extra, minimum = 0) {
  const lang = formData.get("lang") === "en" ? "en" : "fa";
  const slugs = formData.getAll("slug").map(String);
  if (slugs.length < minimum) {
    return { error: message(lang, `Pick at least ${MIN_ITEMS} items to follow.`, "دست‌کم ۳ مورد را برای پیگیری انتخاب کنید.") };
  }
  const watchlist = await send("/api/account/watchlist/", "PUT", { slugs });
  if (!watchlist.ok) return { error: message(lang, "Could not save your watchlist.", "فهرست پیگیری ذخیره نشد.") };
  const account = await send("/api/account/", "PATCH", { dial: formData.get("dial"), ...extra });
  if (!account.ok) {
    const body = await account.json().catch(() => ({}));
    const field = Object.keys(body)[0];
    return { error: message(lang, `Could not save settings${field ? ` (${field})` : ""}.`, `تنظیمات ذخیره نشد${field ? ` (${field})` : ""}.`) };
  }
  return { saved: true };
}

export async function saveOnboarding(_previous, formData) {
  const result = await saveAccount(formData, { onboarded: true }, MIN_ITEMS);
  if (result.error) return result;
  redirect("/");
}

export async function saveSettings(_previous, formData) {
  return saveAccount(formData, {
    quiet_start: formData.get("quiet_start"),
    quiet_end: formData.get("quiet_end"),
    email: String(formData.get("email") || "").trim(),
    email_digest: formData.get("email_digest") === "on",
  });
}

export async function markAllRead() {
  await send("/api/account/inbox/read/", "POST", { all: true });
  redirect("/inbox");
}

/** Deletes the account and everything stored for it, then signs the browser out. */
export async function deleteAccount(formData) {
  if (formData.get("confirm") !== "on") redirect("/settings?delete=confirm");
  const response = await send("/api/account/", "DELETE", {});
  if (!response.ok) redirect("/settings?delete=failed");
  (await cookies()).delete("news_token");
  redirect("/");
}

export async function registerDevice(kind, token) {
  const response = await send("/api/account/devices/", "POST", { kind, token });
  return { ok: response.ok };
}

export async function unregisterDevice(kind, token) {
  const response = await send("/api/account/devices/", "DELETE", { kind, token });
  return { ok: response.ok };
}
