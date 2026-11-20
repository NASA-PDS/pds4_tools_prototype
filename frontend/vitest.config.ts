import { defineConfig } from "vitest/config";
import react from "@vitejs/plugin-react";

export default defineConfig({
  plugins: [react()],
  test: {
    globals: true,
    environment: "jsdom",
    setupFiles: ["./tests/unit/setup.ts"],
    include: ["tests/unit/**/*.test.{ts,tsx}", "src/**/*.test.{ts,tsx}"],
    // Test names carry [REQ-xx]/[BUG-xx] tags; the JUnit report feeds
    // traceability/trace_matrix.py and TestRail (trcli).
    reporters: ["default", ["junit", { outputFile: "test-results/junit-unit.xml", suiteName: "frontend-unit" }]],
  },
});
