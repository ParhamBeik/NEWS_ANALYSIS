import LoginForm from "./LoginForm";

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
    </div>
  );
}
