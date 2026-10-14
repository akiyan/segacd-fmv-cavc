import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

export default defineConfig({
  build: {
    outDir: "dist/client",
    rollupOptions: { input: { app: "index.html" } },
  },
  worker: { format: "es" },
  optimizeDeps: {
    include: [
      "react",
      "react-dom/client",
      "mediabunny",
      "@mediabunny/aac-encoder",
    ],
  },
  server: {
    host: "0.0.0.0",
    allowedHosts: ["terminal.local", "level-ubuntu.taildb3e9c.ts.net"],
    warmup: {
      clientFiles: ["./src/main.jsx"],
    },
  },
  plugins: [react()],
});
