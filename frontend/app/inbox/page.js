import Link from "next/link";
import { markAllRead } from "@/app/account/actions";
import { Icon, TierBadge, When } from "@/components/reader";
import { apiGet } from "@/lib/api";
import { language, label } from "@/lib/language";
import { digits } from "@/lib/reader";

export const metadata = { title: "هشدارها · News Intelligence" };
export const dynamic = "force-dynamic";

const HELD = {
  quiet: ["Held during quiet hours", "در ساعت سکوت نگه داشته شد"],
  cap: ["Over today's 5 notifications", "بیش از سقف ۵ اعلان امروز"],
};

/** Every alert lands here; those held by quiet hours or the daily cap only land here. */
export default async function InboxPage() {
  const lang = await language();
  const tr = (en, fa) => label(lang, en, fa);
  const inbox = await apiGet("/api/account/inbox/");
  return <div className="mx-auto max-w-3xl space-y-6">
    <header className="flex flex-wrap items-end justify-between gap-3">
      <div>
        <h1 className="text-3xl font-extrabold">{tr("Alerts", "هشدارها")}</h1>
        <p className="mt-1 text-sm text-muted">{inbox.unread
          ? tr(`${inbox.unread} unread`, `${digits(inbox.unread, lang)} خوانده‌نشده`)
          : tr("All caught up.", "همه را دیده‌اید.")}</p>
      </div>
      {inbox.unread ? <form action={markAllRead}>
        <button type="submit" className="rounded-lg border border-line px-3 py-2 text-sm hover:border-accent">{tr("Mark all read", "همه خوانده شد")}</button>
      </form> : null}
    </header>
    {inbox.results.length ? <ol className="space-y-3">
      {inbox.results.map((row) => <li key={row.id}
        className={`relative rounded-2xl border bg-card p-4 ${row.read ? "border-line" : "border-accent-strong"}`}>
        <div className="flex flex-wrap items-center gap-2 text-xs">
          {row.breaking ? <span className="rounded-full bg-red-700 px-2.5 py-0.5 font-semibold text-white">{tr("Breaking", "فوری")}</span> : null}
          {row.kind === "update" ? <span className="rounded-full border border-line px-2.5 py-0.5">{tr("Update", "به‌روزرسانی")}</span> : null}
          <TierBadge tier={row.tier} lang={lang} />
          {row.held ? <span className="text-muted">{tr(...HELD[row.held])}</span> : null}
          {!row.read ? <span className="sr-only">{tr("Unread", "خوانده‌نشده")}</span> : null}
        </div>
        <h2 className="mt-2 font-bold leading-8" dir="auto">
          <Link href={`/events/${row.event.id}`} className="after:absolute after:inset-0 hover:text-accent">
            {lang === "en" && row.event.title_en ? row.event.title_en : row.event.title}
          </Link>
        </h2>
        <p className="mt-1 text-xs text-muted"><When iso={row.created_at} lang={lang} time /></p>
      </li>)}
    </ol> : <div className="rounded-2xl border border-dashed border-line p-12 text-center text-muted">
      <Icon name="bell" className="mx-auto mb-3 h-10 w-10" />
      {tr("No alerts yet. Events on your watchlist that reach your dial appear here.",
        "هنوز هشداری نیست. رویدادهای فهرست پیگیری که به حساسیت انتخابی شما برسند اینجا می‌آیند.")}
      <p className="mt-3"><Link href="/settings" className="text-accent underline underline-offset-4">{tr("Edit watchlist", "ویرایش فهرست پیگیری")}</Link></p>
    </div>}
  </div>;
}
