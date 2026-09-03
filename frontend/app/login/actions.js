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

/**
 * Exchange a username/password for a DRF token and store it httpOnly.
 *
 * The credentials never reach the browser's JavaScript and the token never leaves the
 * server process except as a Set-Cookie the browser cannot read. That is the whole point
 * of doing this in a server action rather than a client fetch.
 */
export async function login(_previous, formData) {
  const username = formData.get("username");
  const password = formData.get("password");
  const next = formData.get("next") || "/";

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

  if (!response.ok) return { error: "Incorrect username or password." };

  const { token } = await response.json();
  (await cookies()).set("news_token", token, {
    httpOnly: true,
    sameSite: "lax",
    // Set over plain HTTP in development, hardened behind TLS in production. Hardcoding
    // `secure: true` would make local development silently fail to log in.
    secure: process.env.NODE_ENV === "production",
    path: "/",
    maxAge: 60 * 60 * 24 * 30,
  });
  redirect(safeNext(next));
}
