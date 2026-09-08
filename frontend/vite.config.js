import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import tailwindcss from "@tailwindcss/vite";

export default defineConfig({
  plugins: [react(), tailwindcss()],
  server: {
    // Proxying /api to the backend keeps the browser talking to one origin in
    // development, so CORS never enters the picture locally. The CORS
    // middleware on the API is for the deployed case, where the two are on
    // different domains.
    proxy: {
      "/api": {
        target: "http://localhost:8000",
        changeOrigin: true,
      },
    },
  },
});
