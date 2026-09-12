import AppShell from "@/components/AppShell";
import { currentUser } from "@/lib/api";
import "./globals.css";

export const metadata = {
  title: "News Intelligence",
  description: "Persian security and macroeconomic news analysis",
};

/**
 * `lang="en" dir="ltr"` on the document, with Persian content marked RTL where it appears.
 *
 * The chrome is English and the content is Persian, so a document-level RTL would mirror
 * every dashboard, table and chart to fix the direction of the headlines. Setting
 * direction at the content boundary is the smaller, correct change.
 */

export default async function RootLayout({ children }) {
  const user = await currentUser();

  return (
    <html lang="en" dir="ltr">
      <body className="min-h-screen bg-slate-950 text-slate-100 antialiased">
        <AppShell user={user}>{children}</AppShell>
      </body>
    </html>
  );
}
