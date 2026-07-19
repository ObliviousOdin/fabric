import { defineConfig, loadEnv } from "vite";
import react from "@vitejs/plugin-react";

export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, process.cwd(), "");
  const gateway = env.VITE_FABRIC_GATEWAY || "http://127.0.0.1:7999";

  return {
    base: "/mobile/",
    build: {
      emptyOutDir: true,
      manifest: true,
      outDir: "../../fabric_cli/mobile_web_dist",
    },
    plugins: [react()],
    resolve: {
      alias: {
        "@": new URL("./src", import.meta.url).pathname,
      },
    },
    server: {
      port: 5175,
      proxy: {
        "/api": {
          changeOrigin: true,
          configure(proxy) {
            proxy.on("proxyReqWs", (request) => {
              request.setHeader("origin", gateway);
            });
          },
          target: gateway,
          ws: true,
        },
        "/auth": {
          changeOrigin: true,
          target: gateway,
        },
      },
    },
    test: {
      environment: "node",
    },
  };
});
