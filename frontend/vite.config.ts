import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

export default defineConfig({
  plugins: [react()],
  server: {
    host: true,
    port: 3000,
    strictPort: true,
    proxy: {
      "/api": "http://backend:8000",
      "/ws": "ws://backend:8000",
    },
  },
});
