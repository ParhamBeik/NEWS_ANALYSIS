import { apiGet } from "@/lib/api";
import { language, label } from "@/lib/language";
import OnboardingForm from "./OnboardingForm";

export const metadata = { title: "شروع · News Intelligence" };
export const dynamic = "force-dynamic";

/** First run: pick at least three watch items and an alert dial, then the personal radar. */
export default async function OnboardingPage() {
  const lang = await language();
  const tr = (en, fa) => label(lang, en, fa);
  const [catalog, account] = await Promise.all([
    apiGet("/api/public/watch-items/"), apiGet("/api/account/"),
  ]);
  return <div className="mx-auto max-w-3xl space-y-6">
    <header>
      <p className="text-sm font-medium text-accent">{tr("One step to your own radar","یک قدم تا رادار شخصی")}</p>
      <h1 className="mt-1 text-3xl font-extrabold">{tr("What do you follow?", "چه چیزهایی را دنبال می‌کنید؟")}</h1>
      <p className="mt-2 text-sm leading-7 text-muted">{tr(
        "Pick at least three assets, actors or themes. Events about them are marked and lifted on your radar, and important ones alert you.",
        "دست‌کم سه دارایی، نهاد یا موضوع را انتخاب کنید. رویدادهای مرتبط در رادار شما علامت می‌خورند و بالاتر می‌آیند، و مهم‌ترین‌ها برایتان هشدار می‌شوند.")}</p>
    </header>
    <OnboardingForm items={catalog.results} selected={account.watchlist.map((item) => item.slug)}
      dial={account.dial} lang={lang} />
  </div>;
}
