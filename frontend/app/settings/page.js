import { deleteAccount } from "@/app/account/actions";
import { apiGet } from "@/lib/api";
import { language, label } from "@/lib/language";
import SettingsForm, { BrowserPush } from "./SettingsForm";

export const metadata = { title: "فهرست پیگیری و هشدار · News Intelligence" };
export const dynamic = "force-dynamic";

export default async function SettingsPage({ searchParams }) {
  const params = await searchParams;
  const lang = await language();
  const tr = (en, fa) => label(lang, en, fa);
  const [catalog, account, alertConfig] = await Promise.all([
    apiGet("/api/public/watch-items/"), apiGet("/api/account/"), apiGet("/api/public/alert-config/"),
  ]);
  return <div className="mx-auto max-w-3xl space-y-10">
    <header>
      <h1 className="text-3xl font-extrabold">{tr("Watchlist and alerts", "فهرست پیگیری و هشدارها")}</h1>
      {account.phone ? <p className="mt-2 text-sm text-muted">{tr("Signed in as", "واردشده با")} <span dir="ltr">{account.phone}</span></p> : null}
    </header>
    <SettingsForm items={catalog.results} account={account} lang={lang} />
    <BrowserPush publicKey={alertConfig.public_key} lang={lang} />
    <section className="space-y-3 rounded-2xl border border-red-900/60 p-5">
      <h2 className="text-lg font-bold">{tr("Delete account", "حذف حساب")}</h2>
      <p className="text-sm leading-7 text-muted">{tr(
        "Deletes your phone number, email, watchlist, devices and alerts now. This cannot be undone.",
        "شمارهٔ موبایل، ایمیل، فهرست پیگیری، دستگاه‌ها و هشدارهای شما همین حالا پاک می‌شوند. این کار برگشت‌پذیر نیست.")}</p>
      {params?.delete === "failed" ? <p role="alert" className="text-sm text-red-400">{tr("Deletion failed. Staff accounts are removed by an administrator.", "حذف انجام نشد. حساب کارکنان را مدیر حذف می‌کند.")}</p> : null}
      <form action={deleteAccount} className="flex flex-wrap items-center gap-3">
        <label className="flex items-center gap-2 text-sm">
          <input type="checkbox" name="confirm" required />{tr("I understand", "متوجه هستم")}
        </label>
        <button type="submit" className="rounded-lg bg-red-700 px-4 py-2 text-sm font-semibold text-white hover:bg-red-600">
          {tr("Delete my account", "حذف حساب من")}
        </button>
      </form>
    </section>
  </div>;
}
