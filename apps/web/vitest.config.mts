import react from "@vitejs/plugin-react";
import { defineConfig } from "vitest/config";

export default defineConfig({
  plugins: [react()],
  // Resolve the "@/..." import alias from tsconfig.json.
  resolve: { tsconfigPaths: true },
  test: {
    environment: "jsdom",
    // Unit and component tests only. e2e/ belongs to Playwright.
    include: ["src/**/*.test.{ts,tsx}"],
    setupFiles: ["./vitest.setup.ts"],
  },
});
