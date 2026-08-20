import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  // Produces .next/standalone for a minimal, self-contained Docker image.
  output: "standalone",
  // Pin tracing to this project so Next doesn't infer the workspace root from
  // a lockfile further up the monorepo.
  outputFileTracingRoot: __dirname,
};

export default nextConfig;
