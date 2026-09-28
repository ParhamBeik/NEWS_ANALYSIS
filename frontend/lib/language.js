import { cookies } from "next/headers";

export async function language() {
  return (await cookies()).get("news_language")?.value === "fa" ? "fa" : "en";
}

export function label(lang, english, persian) {
  return lang === "fa" ? persian : english;
}
