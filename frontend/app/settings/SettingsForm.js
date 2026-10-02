"use client";

import { useActionState, useEffect, useState } from "react";
import { useFormStatus } from "react-dom";
import { registerDevice, saveSettings, unregisterDevice } from "@/app/account/actions";
import { decodeKey } from "@/components/AlertOptIn";
import { DialPicker, WatchPicker } from "@/components/WatchPicker";

const input = "rounded-xl border border-line bg-card px-3 py-2 text-sm outline-none focus:border-accent";

function Submit({ fa }) {
  const { pending } = useFormStatus();
  return <button type="submit" disabled={pending}
    className="rounded-xl bg-accent-strong px-5 py-3 font-semibold text-white focus-visible:outline-2 focus-visible:outline-accent disabled:opacity-50">
    {pending ? (fa ? "در حال ذخیره…" : "Saving…") : (fa ? "ذخیرهٔ تنظیمات" : "Save settings")}
  </button>;
}

export default function SettingsForm({ items, account, lang }) {
  const [state, action] = useActionState(saveSettings, {});
  const fa = lang !== "en";
  return <form action={action} className="space-y-8">
    <input type="hidden" name="lang" value={lang} />
    <section className="space-y-3">
      <h2 className="text-xl font-bold">{fa ? "فهرست پیگیری" : "Watchlist"}</h2>
      <WatchPicker items={items} selected={account.watchlist.map((item) => item.slug)} lang={lang} />
    </section>
    <DialPicker value={account.dial} lang={lang} />
    <fieldset className="space-y-2">
      <legend className="mb-2 text-base font-bold">{fa ? "ساعت سکوت (به وقت تهران)" : "Quiet hours (Tehran time)"}</legend>
      <p className="text-sm text-muted">{fa
        ? "در این ساعت‌ها هشدار فقط در صندوق هشدارها می‌نشیند؛ رویدادهای سطح ۵ همچنان اعلان می‌شوند."
        : "Inside these hours alerts wait in your inbox; tier-5 events still notify you."}</p>
      <div className="flex flex-wrap items-center gap-3" dir="ltr">
        <label className="text-sm">{fa ? "از" : "From"} <input type="time" name="quiet_start" defaultValue={account.quiet_start} className={input} /></label>
        <label className="text-sm">{fa ? "تا" : "To"} <input type="time" name="quiet_end" defaultValue={account.quiet_end} className={input} /></label>
      </div>
    </fieldset>
    <fieldset className="space-y-2">
      <legend className="mb-2 text-base font-bold">{fa ? "خلاصهٔ روزانه با ایمیل (اختیاری)" : "Daily email digest (optional)"}</legend>
      <input type="email" name="email" defaultValue={account.email} dir="ltr" placeholder="you@example.com" className={`${input} w-full max-w-sm`} />
      <label className="flex items-center gap-2 text-sm">
        <input type="checkbox" name="email_digest" defaultChecked={account.email_digest} />
        {fa ? "هر صبح خلاصهٔ هشدارهای روز قبل را بفرست" : "Email me yesterday's alerts each morning"}
      </label>
    </fieldset>
    {state.error ? <p role="alert" className="rounded-xl border border-red-800 bg-red-950/60 px-3 py-2 text-sm text-red-200">{state.error}</p> : null}
    {state.saved ? <p role="status" className="text-sm text-accent">{fa ? "ذخیره شد." : "Saved."}</p> : null}
    <Submit fa={fa} />
  </form>;
}

/** Web push for this browser, registered as a `webpush` device on the account. */
export function BrowserPush({ publicKey, lang }) {
  const fa = lang !== "en";
  const [supported, setSupported] = useState(false);
  const [subscription, setSubscription] = useState(null);
  const [message, setMessage] = useState("");
  useEffect(() => {
    if (!("serviceWorker" in navigator && "PushManager" in window)) return;
    setSupported(true);
    navigator.serviceWorker.getRegistration("/sw.js")
      .then((worker) => worker?.pushManager.getSubscription())
      .then((current) => setSubscription(current || null)).catch(() => {});
  }, []);
  if (!publicKey || !supported) return null;

  async function toggle() {
    setMessage("");
    try {
      const worker = await navigator.serviceWorker.register("/sw.js");
      if (subscription) {
        await unregisterDevice("webpush", subscription.toJSON());
        await subscription.unsubscribe();
        setSubscription(null);
        return;
      }
      if (await Notification.requestPermission() !== "granted") throw new Error("denied");
      const next = await worker.pushManager.subscribe({ userVisibleOnly: true, applicationServerKey: decodeKey(publicKey) });
      if (!(await registerDevice("webpush", next.toJSON())).ok) throw new Error("register");
      setSubscription(next);
    } catch {
      setMessage(fa ? "اعلان مرورگر تنظیم نشد. مجوز مرورگر را بررسی کنید." : "Could not set up browser notifications. Check the browser permission.");
    }
  }

  return <div className="flex flex-wrap items-center justify-between gap-3 rounded-xl border border-line bg-card p-4 text-sm">
    <span>{fa ? "اعلان روی همین مرورگر" : "Notifications on this browser"}</span>
    <button type="button" onClick={toggle} className="rounded-lg border border-line px-3 py-2 hover:border-accent">
      {subscription ? (fa ? "خاموش کردن" : "Turn off") : (fa ? "روشن کردن" : "Turn on")}
    </button>
    {message ? <p role="alert" className="basis-full text-red-400">{message}</p> : null}
  </div>;
}
