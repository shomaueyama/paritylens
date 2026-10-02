import type { NextConfig } from "next";

// Where the Next.js server reaches the FastAPI backend. Not exposed to the
// browser: the browser only ever talks to this app's own origin.
const apiInternalUrl = process.env.API_INTERNAL_URL ?? "http://localhost:8000";

const nextConfig: NextConfig = {
  // Emit a self-contained server bundle so the Docker image does not need node_modules.
  output: "standalone",

  // Forward /api/* to the backend. The browser sees one origin, so there is
  // no CORS setup and session cookies stay first-party.
  // Note: this is resolved at build time, so API_INTERNAL_URL must be set
  // when the image is built, not only when it runs.
  async rewrites() {
    return [{ source: "/api/:path*", destination: `${apiInternalUrl}/api/:path*` }];
  },
};

export default nextConfig;
