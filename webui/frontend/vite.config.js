import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// Proxies /api/* to the Flask backend (python -m webui.app, port 5000) so
// the dev server can be opened directly with no CORS setup needed on this
// side (the Flask side still allows CORS too, for a built/served bundle
// hitting it directly).
export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: {
      "/api": "http://127.0.0.1:5000",
    },
  },
});
