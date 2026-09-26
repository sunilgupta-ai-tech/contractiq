// One id per build, compiled into both the browser code and the server, so an
// open tab can tell when a newer build has been deployed (see
// lib/stale-build.ts). CI can pass a git SHA as BUILD_ID.
const buildId = process.env.BUILD_ID || Date.now().toString(36);

/** @type {import('next').NextConfig} */
const nextConfig = {
  // Standalone output: the Docker image ships only the traced server files.
  output: "standalone",
  generateBuildId: async () => buildId,
  env: { NEXT_PUBLIC_BUILD_ID: buildId },
  reactStrictMode: true,
  poweredByHeader: false,
  async headers() {
    return [
      {
        source: "/:path*",
        headers: [
          { key: "X-Content-Type-Options", value: "nosniff" },
          { key: "X-Frame-Options", value: "DENY" },
          { key: "Referrer-Policy", value: "strict-origin-when-cross-origin" },
        ],
      },
    ];
  },
};

export default nextConfig;
