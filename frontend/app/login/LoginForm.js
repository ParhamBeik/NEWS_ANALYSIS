"use client";

import { useActionState } from "react";
import { useFormStatus } from "react-dom";
import { login } from "./actions";

function Submit() {
  const { pending } = useFormStatus();
  return (
    <button
      type="submit"
      disabled={pending}
      className="w-full rounded-lg bg-emerald-500 px-4 py-2 text-sm font-medium text-slate-950 transition hover:bg-emerald-400 disabled:opacity-50"
    >
      {pending ? "Signing in…" : "Sign in"}
    </button>
  );
}

export default function LoginForm({ next }) {
  const [state, action] = useActionState(login, {});
  return (
    <form action={action} className="space-y-3">
      <input type="hidden" name="next" value={next} />
      <input
        name="username"
        autoComplete="username"
        autoFocus
        placeholder="Username"
        className="w-full rounded-lg border border-slate-800 bg-slate-900 px-3 py-2 text-sm outline-none focus:border-emerald-600"
      />
      <input
        name="password"
        type="password"
        autoComplete="current-password"
        placeholder="Password"
        className="w-full rounded-lg border border-slate-800 bg-slate-900 px-3 py-2 text-sm outline-none focus:border-emerald-600"
      />
      {state?.error && (
        <p className="rounded-lg border border-rose-900 bg-rose-950 px-3 py-2 text-xs text-rose-300">
          {state.error}
        </p>
      )}
      <Submit />
    </form>
  );
}
