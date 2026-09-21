import { defineConfig } from "vitest/config";
import { fileURLToPath } from "node:url";

export default defineConfig({
  test: {
    environment: "jsdom",
    setupFiles: ["./tests/setup.ts"],
  },
  resolve: {
    alias: {
      obsidian: fileURLToPath(new URL("./tests/obsidian.ts", import.meta.url)),
    },
  },
});
