import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// Served by the API at /app (same origin, same sign-in). `npm run dev` proxies the API.
export default defineConfig({
  base: "/app/",
  plugins: [react()],
  server: {
    port: 5173,
    proxy: { "/api": "http://localhost:8000" },
    fs: { allow: [".."] }, // the design tokens and fonts live in ../design/shared
  },
  build: { outDir: "dist", emptyOutDir: true, sourcemap: false },
});
