"use client";

import { unstable_rethrow, useRouter } from "next/navigation";
import { Component, Suspense } from "react";

/**
 * One independently-failing, independently-streaming region of a page.
 *
 * Two problems this solves, both of which the app had:
 *
 * 1. ONE SLOW CALL HELD THE WHOLE PAGE. Every page awaited all of its data before emitting
 *    a byte, so time-to-first-byte was the slowest endpoint. The feed - the page people
 *    actually live on - waited on `/api/ops/`, the heaviest aggregate in the system, to
 *    render four header numbers. The Caddyfile already sets `flush_interval -1` precisely
 *    so streaming works; nothing streamed, so that setting bought nothing.
 *
 * 2. ONE FAILING CALL DESTROYED THE WHOLE PAGE. `apiGet` throws on a non-ok status and the
 *    route-level error boundary replaces everything, so a 400 from a single filter turned
 *    the entire feed into an error screen - which is exactly what the mistyped notify value
 *    did in production. A panel should fail as a panel.
 *
 * `unstable_rethrow` is the load-bearing detail. `redirect()` and `notFound()` signal
 * themselves by THROWING, and a custom error boundary will happily catch those and render
 * "something failed" instead of navigating. Re-throwing them hands control back to the
 * framework, so an expired token still reaches the login screen rather than dying here as
 * a red box.
 *
 * On the message shown: a production build REDACTS the text of any error thrown in a
 * server component before it reaches the browser, leaving only a digest. That is not a
 * setting to turn off - it is there so a stack trace or a connection string cannot be
 * served to a client. The real message goes to the server log with the same digest beside
 * it, so the digest is printed here as the thing to grep for. Promising the operator the
 * real text on this screen would be a promise the framework does not keep.
 */

function PanelError({ label, error, onRetry }) {
  const router = useRouter();
  return (
    <div className="rounded-xl border border-rose-900/60 bg-rose-950/20 p-4">
      <div className="flex items-baseline justify-between gap-3">
        <span className="text-sm font-medium text-rose-200">
          {label ? `${label} unavailable` : "This section failed to load"}
        </span>
        <button
          type="button"
          onClick={() => {
            onRetry();
            router.refresh();
          }}
          className="rounded-md bg-rose-900/70 px-2 py-1 text-xs text-rose-100 hover:bg-rose-800"
        >
          Retry
        </button>
      </div>
      <pre className="mt-2 overflow-x-auto whitespace-pre-wrap text-[11px] text-rose-300/70">
        {error?.digest
          ? `Server error ${error.digest} — the full message is in the frontend container log under this digest:\ndocker compose -f docker-compose.prod.yml logs frontend | grep ${error.digest}`
          : error?.message || String(error)}
      </pre>
      <p className="mt-2 text-[11px] text-rose-300/50">
        The rest of this page is unaffected.
      </p>
    </div>
  );
}

class Boundary extends Component {
  state = { error: null };

  static getDerivedStateFromError(error) {
    // Throws straight back out for NEXT_REDIRECT / NEXT_NOT_FOUND, so framework
    // navigation is never mistaken for an application error.
    unstable_rethrow(error);
    return { error };
  }

  render() {
    if (this.state.error) {
      return (
        <PanelError
          label={this.props.label}
          error={this.state.error}
          onRetry={() => this.setState({ error: null })}
        />
      );
    }
    return this.props.children;
  }
}

export default function AsyncPanel({ children, fallback = null, label }) {
  return (
    <Boundary label={label}>
      <Suspense fallback={fallback}>{children}</Suspense>
    </Boundary>
  );
}

/** A placeholder with the same footprint as the content it stands in for, so the layout
 *  does not jump when the real thing arrives. */
export function Skeleton({ className = "" }) {
  return <div className={`animate-pulse rounded-xl bg-slate-800/50 ${className}`} />;
}
