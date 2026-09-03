"use client";

/**
 * Shows the real error text.
 *
 * A generic "something went wrong" on an internal operations tool is a bad trade: this app
 * is behind a single login, the reader is the operator, and hiding "connection refused to
 * backend:8000" from them costs a debugging session to save nothing.
 */
export default function Error({ error, reset }) {
  return (
    <div className="mx-auto mt-20 max-w-xl rounded-xl border border-rose-900 bg-rose-950/30 p-6">
      <h1 className="text-lg font-semibold text-rose-200">Something failed</h1>
      <pre className="mt-3 overflow-x-auto whitespace-pre-wrap text-xs text-rose-300/80">
        {error?.message || String(error)}
      </pre>
      <button
        onClick={reset}
        className="mt-4 rounded-lg bg-rose-900 px-3 py-1.5 text-sm text-rose-100 hover:bg-rose-800"
      >
        Try again
      </button>
    </div>
  );
}
