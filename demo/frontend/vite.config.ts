/// <reference types="vitest/config" />
import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

/** Minimal source map to silence 404 for Monaco loader.js.map (browser requests it for devtools). */
const EMPTY_SOURCE_MAP = JSON.stringify({
  version: 3,
  sources: [],
  names: [],
  mappings: "",
});

function monacoLoaderSourceMapPlugin() {
  const handler = (
    req: { url?: string },
    res: { setHeader: (a: string, b: string) => void; end: (b: string) => void },
    next: () => void
  ) => {
    const pathname = (req.url ?? "").split("?")[0].split("#")[0];
    if (pathname.endsWith("loader.js.map")) {
      res.setHeader("Content-Type", "application/json");
      res.end(EMPTY_SOURCE_MAP);
      return;
    }
    next();
  };
  return {
    name: "monaco-loader-sourcemap",
    configureServer(server: { middlewares: { use: (fn: typeof handler) => void } }) {
      server.middlewares.use(handler);
    },
    configurePreviewServer(server: { middlewares: { use: (fn: typeof handler) => void } }) {
      server.middlewares.use(handler);
    },
  };
}

export default defineConfig({
  plugins: [monacoLoaderSourceMapPlugin(), react()],
  server: {
    port: parseInt(process.env.PORT || "5173", 10),
    proxy: {
      "/api": {
        target: process.env.VITE_API_TARGET || "http://localhost:8000",
        changeOrigin: true,
      },
    },
  },
  test: {
    environment: "jsdom",
    globals: true,
    setupFiles: ["./tests/setup.ts"],
    exclude: ["**/node_modules/**", "**/e2e/**"],
  },
});
