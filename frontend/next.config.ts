import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  reactStrictMode: true,
  // The native watcher misses writes made by other processes on this Windows setup,
  // which left the dev server serving stale code. Polling is the reliable fallback.
  watchOptions: { pollIntervalMs: 400 },
  async headers() {
    if (process.env.NODE_ENV !== "development") return [];
    return [
      {
        source: "/:path*",
        headers: [
          {
            key: "Cache-Control",
            value: "no-store, must-revalidate",
          },
        ],
      },
    ];
  },
};

export default nextConfig;
