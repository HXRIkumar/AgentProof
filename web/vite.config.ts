import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

export default defineConfig(({ mode }) => ({
  define: { "import.meta.env.VITE_RECORDED_ONLY": JSON.stringify(mode === "recorded" ? "true" : "false") },
  plugins: [react()],
  server: { proxy: { "/api": "http://127.0.0.1:8010" } },
}));
