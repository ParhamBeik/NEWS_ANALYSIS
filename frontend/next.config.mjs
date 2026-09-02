/** @type {import('next').NextConfig} */
const nextConfig = {
  output: "standalone",
  async rewrites() {
    return [{ source: "/api/:path*", destination: `${process.env.API_ORIGIN || "http://backend:8000"}/api/:path*` }];
  }
};
export default nextConfig;
