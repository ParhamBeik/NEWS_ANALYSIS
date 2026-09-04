"use client";

/**
 * The last-resort boundary: a failure that escaped every `AsyncPanel` on the page.
 *
 * It shows whatever the framework actually gives it. A production build redacts the text
 * of an error thrown in a server component before it reaches the browser and replaces it
 * with a digest - deliberately, so a stack trace or a connection string is never served to
 * a client - and writes the real message to the server log beside that same digest. So the
 * digest is what is printed here, with the command that turns it back into the error.
 *
 * Showing a bare "something went wrong" would be the wrong trade for an internal tool with
 * one operator reading it; showing a message the framework never provided would be worse,
 * because it reads as though the detail is missing rather than deliberately elsewhere.
 */
export default function Error({ error, reset }) {
  return (
    <div className="mx-auto mt-20 max-w-xl rounded-xl border border-rose-900 bg-rose-950/30 p-6">
      <h1 className="text-lg font-semibold text-rose-200">This page failed to render</h1>
      <pre className="mt-3 overflow-x-auto whitespace-pre-wrap text-xs text-rose-300/80">
        {error?.digest
          ? `Server error ${error.digest}\n\nThe full message is in the frontend container log:\ndocker compose -f docker-compose.prod.yml logs frontend | grep ${error.digest}`
          : error?.message || String(error)}
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
