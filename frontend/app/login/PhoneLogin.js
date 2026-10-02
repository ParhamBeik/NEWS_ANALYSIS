"use client";

import { useActionState } from "react";
import { useFormStatus } from "react-dom";
import { phoneLogin } from "./actions";

const field = "w-full rounded-xl border border-line bg-card px-4 py-3 text-base text-ink outline-none focus:border-accent";

function Submit({ children, busy }) {
  const { pending } = useFormStatus();
  return <button type="submit" disabled={pending}
    className="w-full rounded-xl bg-accent-strong px-4 py-3 text-base font-semibold text-white transition hover:opacity-90 focus-visible:outline-2 focus-visible:outline-accent disabled:opacity-50">
    {pending ? busy : children}
  </button>;
}

/** Two steps, one form: mobile number, then the texted code. */
export default function PhoneLogin({ next, lang }) {
  const [state, action] = useActionState(phoneLogin, { step: "phone" });
  const fa = lang !== "en";
  const onCode = state.step === "code";
  return <form action={action} className="space-y-3">
    <input type="hidden" name="next" value={next} />
    <input type="hidden" name="lang" value={lang} />
    <label htmlFor="phone" className="block text-sm font-medium text-ink">{fa ? "شمارهٔ موبایل" : "Mobile number"}</label>
    <input id="phone" name="phone" type="tel" inputMode="tel" autoComplete="tel" dir="ltr" required
      readOnly={onCode} defaultValue={state.phone || ""} placeholder="0912 123 4567"
      className={`${field} text-left tabular ${onCode ? "opacity-70" : ""}`} autoFocus={!onCode} />
    {onCode ? <>
      <label htmlFor="code" className="block text-sm font-medium text-ink">{fa ? "کد پیامک‌شده" : "Code we texted you"}</label>
      <input id="code" name="code" inputMode="numeric" autoComplete="one-time-code" dir="ltr" required
        maxLength={6} pattern="[0-9۰-۹]{6}" autoFocus placeholder="••••••"
        className={`${field} text-center text-xl tracking-[0.5em] tabular`} />
    </> : null}
    {state.error ? <p role="alert" className="rounded-xl border border-red-800 bg-red-950/60 px-3 py-2 text-sm text-red-200">{state.error}</p> : null}
    {onCode && !state.error ? <p role="status" className="text-sm text-muted">{fa ? "کد ۶ رقمی برایتان پیامک شد؛ تا ۲ دقیقه معتبر است." : "We texted a 6-digit code; it is valid for 2 minutes."}</p> : null}
    <Submit busy={fa ? "صبر کنید…" : "Please wait…"}>
      {onCode ? (fa ? "ورود" : "Sign in") : (fa ? "دریافت کد" : "Send code")}
    </Submit>
    {onCode ? <button type="submit" formNoValidate name="resend" value="1"
      className="w-full text-sm text-muted underline underline-offset-4 hover:text-ink">
      {fa ? "ارسال دوبارهٔ کد" : "Send the code again"}
    </button> : null}
  </form>;
}
