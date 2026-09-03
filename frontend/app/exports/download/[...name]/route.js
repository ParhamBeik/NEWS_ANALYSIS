import { apiFetch } from "@/lib/api";

/**
 * Stream a workbook from Django through Next.
 *
 * The browser holds no API token - that is the whole point of keeping it httpOnly and
 * server-side - so it cannot fetch from Django directly. This handler attaches the token,
 * then pipes the body straight through without buffering it, so a large workbook does not
 * sit in the Node process's memory.
 *
 * A CATCH-ALL segment, because the exporter writes into the subdirectories the team files
 * by - `Excel Files/…`, `TXT Files/…` - and an export name is therefore a path. Encoding
 * that slash into a single `[name]` segment relies on `%2F` surviving normalisation, which
 * is exactly the kind of thing a proxy in front of Node is entitled to rewrite.
 */
export async function GET(request, { params }) {
  const { name } = await params;
  const segments = Array.isArray(name) ? name : [name];
  const path = segments.map(encodeURIComponent).join("/");
  const upstream = await apiFetch(`/api/exports/${path}/`);
  if (!upstream.ok) {
    return new Response("Not found", { status: upstream.status });
  }
  // The basename only: a Content-Disposition filename carrying a directory is either
  // ignored or sanitised, and the browser would save it under a name nobody recognises.
  const filename = segments[segments.length - 1];
  return new Response(upstream.body, {
    headers: {
      "Content-Type":
        upstream.headers.get("content-type") || "application/octet-stream",
      "Content-Disposition": `attachment; filename*=UTF-8''${encodeURIComponent(filename)}`,
    },
  });
}
