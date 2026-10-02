import localFont from "next/font/local";
import AppShell from "@/components/AppShell";
import ServiceWorker from "@/components/ServiceWorker";
import { currentUser } from "@/lib/api";
import { language } from "@/lib/language";
import "./globals.css";

// Bundled, not fetched from Google: the reader is served from Iran.
const vazirmatn = localFont({
  src: "./fonts/Vazirmatn.woff2",
  weight: "100 900",
  display: "swap",
  variable: "--font-vazirmatn",
});

export const metadata = {
  title: "News Intelligence",
  description: "Iran-focused economic and geopolitical news intelligence",
  appleWebApp: { capable: true, title: "رادار خبر", statusBarStyle: "black-translucent" },
};

export const viewport = { themeColor: "#4b33c9" };

/**
 * Document direction follows the reader's chosen language. Headlines from another
 * language use `dir="auto"` at their own text boundary.
 */

export default async function RootLayout({ children }) {
  const user = await currentUser();
  const lang = await language();

  return (
    <html lang={lang} dir={lang === "fa" ? "rtl" : "ltr"} className={vazirmatn.variable}>
      <body className="min-h-screen font-sans">
        <AppShell user={user} lang={lang}>{children}</AppShell>
        <ServiceWorker />
      </body>
    </html>
  );
}
