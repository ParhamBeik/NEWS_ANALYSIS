import { apiFetch } from "@/lib/api";

/**
 * Stream a workbook from Django through Next.
 *
 * The browser holds no API token - that is the whole point of keeping it httpOnly and
 * server-side - so it cannot fetch from Django directly. This handler attaches the token,
 * then pipes the body straight through without buffering it, so a large workbook does not
 * sit in the Node process's memory.
 */
export async function GET(request, { params }) {
  const { name } = await params;
  const upstream = await apiFetch(`/api/exports/${encodeURIComponent(name)}/`);
  if (!upstream.ok) {
    return new Response("Not found", { status: upstream.status });
  }
  return new Response(upstream.body, {
    headers: {
      "Content-Type":
        upstream.headers.get("content-type") || "application/octet-stream",
      "Content-Disposition": `attachment; filename="${name}"`,
    },
  });
}
