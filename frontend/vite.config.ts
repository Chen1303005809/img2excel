import { defineConfig, loadEnv } from "vite";
import react from "@vitejs/plugin-react";

export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, "..", "IMAGE_TABLE_");
  const backendHost = env.IMAGE_TABLE_BACKEND_HOST ?? "127.0.0.1";
  const backendPort = env.IMAGE_TABLE_BACKEND_PORT ?? "8000";
  const frontendHost = env.IMAGE_TABLE_FRONTEND_HOST ?? "127.0.0.1";
  const frontendPort = Number(env.IMAGE_TABLE_FRONTEND_PORT ?? "5173");

  return {
    plugins: [react()],
    server: {
      host: frontendHost,
      port: frontendPort,
      proxy: {
        "/api": `http://${backendHost}:${backendPort}`,
      },
    },
  };
});
