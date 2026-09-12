import Link from "next/link";
import SignupForm from "./SignupForm";

export const metadata = { title: "Create account · News Intelligence" };

export default async function SignupPage({ searchParams }) {
  const params = await searchParams;
  const next = params?.next || "/";
  const loginHref =
    next && next !== "/"
      ? `/login?next=${encodeURIComponent(next)}`
      : "/login";

  return (
    <div className="mx-auto mt-24 max-w-sm px-3">
      <h1 className="text-xl font-semibold text-slate-100">Create account</h1>
      <p className="mt-1 mb-6 text-sm text-slate-400">
        Join the News Intelligence workspace.
      </p>
      <SignupForm next={next} />
      <p className="mt-4 text-center text-sm text-slate-400">
        Already registered?{" "}
        <Link href={loginHref} className="text-emerald-400 underline underline-offset-2 hover:text-emerald-300">
          Sign in
        </Link>
      </p>
    </div>
  );
}
