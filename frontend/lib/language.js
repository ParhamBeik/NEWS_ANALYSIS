import { cookies, headers } from "next/headers";

export async function language() {
  const saved = (await cookies()).get("news_language")?.value;
  if (saved === "fa" || saved === "en") return saved;
  const preferred = (await headers()).get("accept-language")?.split(",")[0]?.toLowerCase() || "";
  return preferred.startsWith("en") ? "en" : "fa";
}

export function label(lang, english, persian) {
  return lang === "fa" ? persian : english;
}
