"use client";

import { useActionState } from "react";
import { useFormStatus } from "react-dom";
import { saveOnboarding } from "@/app/account/actions";
import { DialPicker, WatchPicker } from "@/components/WatchPicker";

function Submit({ lang }) {
  const { pending } = useFormStatus();
  return <button type="submit" disabled={pending}
    className="w-full rounded-xl bg-accent-strong px-5 py-3 font-semibold text-white focus-visible:outline-2 focus-visible:outline-accent disabled:opacity-50 sm:w-auto">
    {pending ? (lang === "en" ? "Saving…" : "در حال ذخیره…") : (lang === "en" ? "Show my radar" : "نمایش رادار من")}
  </button>;
}

export default function OnboardingForm({ items, selected, dial, lang }) {
  const [state, action] = useActionState(saveOnboarding, {});
  return <form action={action} className="space-y-8">
    <input type="hidden" name="lang" value={lang} />
    <WatchPicker items={items} selected={selected} lang={lang} />
    <DialPicker value={dial} lang={lang} />
    {state.error ? <p role="alert" className="rounded-xl border border-red-800 bg-red-950/60 px-3 py-2 text-sm text-red-200">{state.error}</p> : null}
    <Submit lang={lang} />
  </form>;
}
