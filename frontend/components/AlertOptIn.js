"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { removeAlertSubscription, saveAlertSubscription } from "@/app/alerts/actions";

const CLASSES = ["fx", "gold", "tehran_index", "oil", "bitcoin"];

function decodeKey(value) {
  const padded = value.replace(/-/g, "+").replace(/_/g, "/");
  const bytes = atob(padded + "=".repeat((4 - padded.length % 4) % 4));
  return Uint8Array.from(bytes, (byte) => byte.charCodeAt(0));
}

export default function AlertOptIn({ publicKey, signedIn, lang }) {
  const [subscribed, setSubscribed] = useState(false);
  const [supported, setSupported] = useState(false);
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState("");
  const [globalEvents, setGlobalEvents] = useState(false);
  const [assets, setAssets] = useState([]);
  const fa = lang === "fa";

  useEffect(() => {
    const available = "serviceWorker" in navigator && "PushManager" in window && "Notification" in window;
    setSupported(available);
    if (!available) return;
    navigator.serviceWorker.getRegistration("/sw.js")
      .then((worker) => worker?.pushManager.getSubscription())
      .then((subscription) => setSubscribed(Boolean(subscription))).catch(() => {});
  }, []);

  if (!publicKey || !supported) return null;
  if (!signedIn) return <p className="text-xs text-muted">
    <Link href="/login" className="text-accent underline">{fa ? "وارد شوید" : "Sign in"}</Link>
    {fa ? " تا هشدارهای اختیاری را فعال کنید." : " to opt in to important news alerts."}
  </p>;

  async function toggle() {
    setBusy(true); setMessage("");
    try {
      const worker = await navigator.serviceWorker.register("/sw.js");
      const current = await worker.pushManager.getSubscription();
      if (subscribed && current) {
        const result = await removeAlertSubscription(current.endpoint);
        if (!result.removed) throw new Error("unsubscribe_failed");
        await current.unsubscribe(); setSubscribed(false);
      } else {
        if (await Notification.requestPermission() !== "granted") throw new Error("permission_denied");
        const next = current || await worker.pushManager.subscribe({
          userVisibleOnly: true, applicationServerKey: decodeKey(publicKey),
        });
        const result = await saveAlertSubscription(next.toJSON(), {
          iran: true, global_events: globalEvents, asset_classes: assets,
        });
        if (result.error) throw new Error(result.error);
        setSubscribed(true);
      }
    } catch {
      setMessage(fa ? "تنظیم هشدار انجام نشد. مجوز مرورگر و اتصال را بررسی کنید." : "Could not update alerts. Check browser permission and connection.");
    } finally { setBusy(false); }
  }

  return <div className="rounded-2xl border border-line bg-card p-4 text-sm">
    <div className="flex flex-wrap items-center justify-between gap-3">
      <div><strong>{fa ? "هشدار خبرهای مهم ایران" : "Top Iran news alerts"}</strong>
        <p className="text-xs text-muted">{fa ? "اختیاری؛ فقط رویدادهای با اطمینان بالا." : "Opt in to high-confidence events."}</p></div>
      <button type="button" onClick={toggle} disabled={busy}
        className="rounded-lg bg-accent-strong px-3 py-2 text-white focus-visible:outline-2 focus-visible:outline-accent disabled:opacity-50">
        {subscribed ? (fa ? "خاموش کردن" : "Turn off") : (fa ? "فعال کردن" : "Turn on")}
      </button>
    </div>
    {!subscribed && <div className="mt-3 flex flex-wrap gap-3 text-xs text-muted">
      <label><input type="checkbox" checked={globalEvents} onChange={(event) => setGlobalEvents(event.target.checked)} /> {fa ? "جهانی" : "Global"}</label>
      {CLASSES.map((key) => <label key={key}><input type="checkbox" checked={assets.includes(key)}
        onChange={(event) => setAssets(event.target.checked ? [...assets, key] : assets.filter((item) => item !== key))} /> {key.replaceAll("_", " ")}</label>)}
    </div>}
    {message && <p role="status" className="mt-2 text-red-700 dark:text-red-300">{message}</p>}
  </div>;
}
