import Link from "next/link";

export default function NotFound() {
  return (
    <div className="mx-auto mt-24 max-w-md text-center">
      <h1 className="text-lg font-semibold text-slate-200">Not found</h1>
      <p className="mt-2 text-sm text-slate-500">
        That article or page does not exist. It may have been collapsed into another copy by
        the deduplicator.
      </p>
      <Link href="/" className="mt-4 inline-block text-sm text-emerald-400 hover:underline">
        Back to the feed
      </Link>
    </div>
  );
}
