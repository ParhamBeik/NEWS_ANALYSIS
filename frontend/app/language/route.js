import { cookies } from "next/headers";
import { NextResponse } from "next/server";

export async function POST(request) {
  const form = await request.formData();
  const lang = form.get("language") === "fa" ? "fa" : "en";
  const next = form.get("next");
  const path = typeof next === "string" && next.startsWith("/") && !next.startsWith("//")
    ? next : "/";
  (await cookies()).set("news_language", lang, {
    path: "/", sameSite: "lax", httpOnly: true, secure: process.env.NODE_ENV === "production",
  });
  return NextResponse.redirect(new URL(path, request.url), 303);
}
