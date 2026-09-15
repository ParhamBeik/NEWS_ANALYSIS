/** @type {import('next').NextConfig} */

/**
 * No `/api/*` rewrite.
 *
 * Every call to Django happens in a server component or a server action, with the token
 * attached server-side. Proxying the API to the browser as well would put a second,
 * unauthenticated path to the same data one typo away, and would drag CORS and CSRF back
 * into a design that currently needs neither.
 *
 * `/media/*` IS proxied, but only as the development fallback - in production Caddy serves
 * the shared media volume directly and never wakes Node to move image bytes.
 *
 * The API origin is spelled out here rather than imported from lib/api.js, which is where
 * every runtime caller gets it. This file is evaluated by the Next CLI before the `@/`
 * alias in jsconfig.json exists, so the import would resolve at build time only by
 * accident. One deliberate copy, in the one place that cannot share.
 */
const nextConfig = {
  output: "standalone",
  images: { unoptimized: true },
  async rewrites() {
    return {
      fallback: [
        {
          source: "/media/:path*",
          destination: `${process.env.API_ORIGIN || "http://127.0.0.1:8000"}/media/:path*`,
        },
      ],
    };
  },
};

export default nextConfig;
