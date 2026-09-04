"use client";

import { useActionState } from "react";
import { useFormStatus } from "react-dom";
import { signup } from "../login/actions";

function Submit() {
  const { pending } = useFormStatus();
  return (
    <button
      type="submit"
      disabled={pending}
      className="w-full rounded-lg bg-emerald-500 px-4 py-2 text-sm font-medium text-slate-950 transition hover:bg-emerald-400 disabled:opacity-50"
    >
      {pending ? "Creating account…" : "Create account"}
    </button>
  );
}

export default function SignupForm() {
  const [state, action] = useActionState(signup, {});
  const inputClass =
    "w-full rounded-lg border border-slate-800 bg-slate-900 px-3 py-2 text-sm outline-none focus:border-emerald-600";
  return (
    <form action={action} className="space-y-3">
      <input name="username" autoComplete="username" autoFocus required placeholder="Username" className={inputClass} />
      <input name="email" type="email" autoComplete="email" placeholder="Email (optional)" className={inputClass} />
      <input name="password" type="password" autoComplete="new-password" required minLength={8} placeholder="Password" className={inputClass} />
      <input name="passwordConfirm" type="password" autoComplete="new-password" required minLength={8} placeholder="Confirm password" className={inputClass} />
      {state?.error && (
        <p className="rounded-lg border border-rose-900 bg-rose-950 px-3 py-2 text-xs text-rose-300">
          {state.error}
        </p>
      )}
      <Submit />
    </form>
  );
}
