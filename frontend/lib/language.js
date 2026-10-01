import { cookies } from "next/headers";

/** Persian unless the reader chose English. Many Iranian phones run an English browser
 *  locale, so Accept-Language is not a signal of reading preference here. */
export async function language() {
  return (await cookies()).get("news_language")?.value === "en" ? "en" : "fa";
}

export function label(lang, english, persian) {
  return lang === "fa" ? persian : english;
}
