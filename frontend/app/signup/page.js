import Link from "next/link";
import SignupForm from "./SignupForm";

export const metadata = { title: "Create account · News Intelligence" };

export default function SignupPage() {
  return (
    <div className="mx-auto mt-24 max-w-sm">
      <h1 className="text-xl font-semibold text-slate-100">Create account</h1>
      <p className="mt-1 mb-6 text-sm text-slate-500">
        Join the News Intelligence workspace.
      </p>
      <SignupForm />
      <p className="mt-4 text-center text-sm text-slate-500">
        Already registered?{" "}
        <Link href="/login" className="text-emerald-400 hover:underline">
          Sign in
        </Link>
      </p>
    </div>
  );
}
