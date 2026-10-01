import AppShell from "@/components/AppShell";
import { currentUser } from "@/lib/api";
import { language } from "@/lib/language";
import "./globals.css";

export const metadata = {
  title: "News Intelligence",
  description: "Iran-focused economic and geopolitical news intelligence",
};

/**
 * Document direction follows the reader's chosen language. Headlines from another
 * language use `dir="auto"` at their own text boundary.
 */

export default async function RootLayout({ children }) {
  const user = await currentUser();
  const lang = await language();

  return (
    <html lang={lang} dir={lang === "fa" ? "rtl" : "ltr"}>
      <body className="min-h-screen bg-slate-950 text-slate-100 antialiased">
        <AppShell user={user} lang={lang}>{children}</AppShell>
      </body>
    </html>
  );
}
