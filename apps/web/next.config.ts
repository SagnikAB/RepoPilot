import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  async rewrites() {
    // Browser traffic uses the App Router proxy at /api/proxy so ANALYZE
    // requests can exceed the default rewrite timeout. Rewrites are not used.
    return [];
  },
};

export default nextConfig;
