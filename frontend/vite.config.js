import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

export default defineConfig({
  plugins: [react()],
  server: {
    port: 3000,
    // The backend serves HTTPS (self-signed by default, hence secure: false). This dev
    // server itself is plain HTTP, so tell the backend; otherwise its session cookie is
    // marked Secure and the browser drops it. Development only.
    proxy: {
      "/api": {
        target: "https://localhost:9000",
        secure: false,
        rewrite: (p) => p.replace(/^\/api/, ""),
        headers: { "X-Forwarded-Proto": "http" },
      },
      "/ws": { target: "wss://localhost:9000", ws: true, secure: false, headers: { "X-Forwarded-Proto": "http" } },
    },
  },
  build: {
    outDir: "../static",
    emptyOutDir: true,
  },
});
