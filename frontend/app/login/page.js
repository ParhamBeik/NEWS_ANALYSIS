import Link from "next/link";
import { language } from "@/lib/language";
import LoginForm from "./LoginForm";
import PhoneLogin from "./PhoneLogin";

export const metadata = { title: "ورود · News Intelligence" };

/** Readers sign in with their phone; staff keep username and password underneath. */
export default async function LoginPage({ searchParams }) {
  const params = await searchParams;
  const next = params?.next || "/";
  const lang = await language();
  const fa = lang === "fa";
  const signupHref =
    next && next !== "/"
      ? `/signup?next=${encodeURIComponent(next)}`
      : "/signup";

  return (
    <div className="mx-auto mt-16 max-w-sm px-4 sm:mt-24">
      <Link href="/" className="text-sm font-bold tracking-tight text-ink">
        News<span className="text-accent">Intel</span>
      </Link>
      <h1 className="mt-6 text-2xl font-extrabold text-ink">{fa ? "ورود به رادار خبر" : "Sign in to the news radar"}</h1>
      <p className="mt-2 mb-6 text-sm leading-7 text-muted">
        {fa
          ? "با شمارهٔ موبایل وارد شوید تا دارایی‌ها و موضوع‌های مورد نظرتان را دنبال کنید و هشدار بگیرید."
          : "Sign in with your mobile number to follow the assets and topics you care about and get alerts."}
      </p>
      <PhoneLogin next={next} lang={lang} />
      <p className="mt-3 text-center text-sm">
        <Link href={next !== "/" ? `/login?next=${encodeURIComponent(next)}` : "/login"} className="text-muted underline underline-offset-4 hover:text-ink">
          {fa ? "تغییر شماره" : "Use a different number"}
        </Link>
      </p>
      <details className="mt-10 rounded-xl border border-line p-4" dir="ltr">
        <summary className="cursor-pointer text-sm text-muted">{fa ? "ورود کارکنان (نام کاربری)" : "Staff sign-in (username)"}</summary>
        <div className="mt-4">
          <LoginForm next={next} />
          <p className="mt-4 text-center text-sm text-slate-400">
            No account?{" "}
            <Link href={signupHref} className="text-emerald-400 underline underline-offset-2 hover:text-emerald-300">
              Create one
            </Link>
          </p>
        </div>
      </details>
    </div>
  );
}
