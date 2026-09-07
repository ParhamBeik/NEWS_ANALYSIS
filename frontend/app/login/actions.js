"use server";

import { cookies } from "next/headers";
import { redirect } from "next/navigation";

const API_ORIGIN = process.env.API_ORIGIN || "http://127.0.0.1:8000";

/**
 * The post-login destination, or "/" if it is not one of ours.
 *
 * `startsWith("/")` alone is not enough. `//evil.com` and `/\evil.com` both begin with a
 * slash and both are PROTOCOL-RELATIVE URLs: the browser resolves them against the current
 * scheme and lands on another origin, which turns the login screen into an open redirect
 * even though nothing that looks like a scheme was ever supplied.
 */
function safeNext(next) {
  const target = typeof next === "string" ? next : "";
  if (!target.startsWith("/")) return "/";
  if (target.startsWith("//") || target.startsWith("/\\")) return "/";
  return target;
}

function firstError(body) {
  if (!body || typeof body !== "object") return "";
  return Object.values(body).flat().find(Boolean) || "";
}

async function storeToken(token) {
  (await cookies()).set("news_token", token, {
    httpOnly: true,
    sameSite: "lax",
    secure: process.env.NODE_ENV === "production",
    path: "/",
    maxAge: 60 * 60 * 24 * 30,
  });
}

/**
 * Exchange a username/password for a DRF token and store it httpOnly.
 *
 * The credentials never reach the browser's JavaScript and the token never leaves the
 * server process except as a Set-Cookie the browser cannot read. That is the whole point
 * of doing this in a server action rather than a client fetch.
 */
export async function login(_previous, formData) {
  const username = String(formData.get("username") || "").trim();
  const password = String(formData.get("password") || "");
  const next = formData.get("next") || "/";

  if (!username) return { error: "Enter your username." };
  if (!password) return { error: "Enter your password." };

  let response;
  try {
    response = await fetch(`${API_ORIGIN}/api/auth/token/`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ username, password }),
      cache: "no-store",
    });
  } catch {
    // Distinguished from a rejected password on purpose: "the API is down" and "you typed
    // it wrong" have completely different fixes, and one generic message hides both.
    return { error: "Cannot reach the API. Is the backend running?" };
  }

  if (!response.ok) {
    if (response.status === 400) {
      const message = firstError(await response.json().catch(() => null));
      if (message) {
        const lower = message.toLowerCase();
        if (lower.includes("blank") || lower.includes("may not be null")) {
          return { error: !username ? "Enter your username." : "Enter your password." };
        }
        return { error: message };
      }
    }
    return { error: "Incorrect username or password." };
  }

  const { token } = await response.json();
  await storeToken(token);
  redirect(safeNext(next));
}

export async function signup(_previous, formData) {
  const username = String(formData.get("username") || "").trim();
  const email = formData.get("email");
  const password = String(formData.get("password") || "");
  const passwordConfirm = String(formData.get("passwordConfirm") || "");
  const next = formData.get("next") || "/";

  if (!username) return { error: "Enter a username." };
  if (!password) return { error: "Enter a password." };
  if (!passwordConfirm) return { error: "Confirm your password." };
  if (password !== passwordConfirm) {
    return { error: "Passwords do not match." };
  }

  let response;
  try {
    response = await fetch(`${API_ORIGIN}/api/auth/signup/`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ username, email, password }),
      cache: "no-store",
    });
  } catch {
    return { error: "Cannot reach the API. Is the backend running?" };
  }

  const body = await response.json();
  if (!response.ok) {
    const message = firstError(body);
    return { error: message || "Could not create the account." };
  }

  await storeToken(body.token);
  redirect(safeNext(next));
}
