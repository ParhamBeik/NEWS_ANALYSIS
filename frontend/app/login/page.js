import LoginForm from "./LoginForm";
import Link from "next/link";

export const metadata = { title: "Sign in · News Intelligence" };

export default async function LoginPage({ searchParams }) {
  const params = await searchParams;
  return (
    <div className="mx-auto mt-24 max-w-sm">
      <h1 className="text-xl font-semibold text-slate-100">News Intelligence</h1>
      <p className="mt-1 mb-6 text-sm text-slate-500">
        Persian security and macroeconomic news analysis.
      </p>
      <LoginForm next={params?.next || "/"} />
      <p className="mt-4 text-center text-sm text-slate-500">
        No account?{" "}
        <Link href="/signup" className="text-emerald-400 hover:underline">
          Create one
        </Link>
      </p>
    </div>
  );
}
