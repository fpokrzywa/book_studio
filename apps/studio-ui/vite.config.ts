import { readFileSync } from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import react from "@vitejs/plugin-react";
import { defineConfig, type Plugin } from "vite";

const here = path.dirname(fileURLToPath(import.meta.url));
const repoRoot = path.resolve(here, "../..");
const workspace = process.env.PBS_WORKSPACE ?? path.join(repoRoot, ".pbs-data");
const coreUrl = process.env.PBS_CORE_URL ?? "http://127.0.0.1:8765";
const uiPort = Number(process.env.PBS_UI_PORT ?? 5173);

/** Core writes a fresh session token on every launch; read it per request so restarts just work. */
function readToken(): string {
  try {
    return readFileSync(path.join(workspace, "runtime", "session.token"), "utf8").trim();
  } catch {
    return "";
  }
}

/** Strict CSP for production builds (dev needs inline scripts for React Fast Refresh). */
function cspForBuild(): Plugin {
  return {
    name: "pbs-csp",
    apply: "build",
    transformIndexHtml(html) {
      const csp =
        "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; " +
        "font-src 'self'; connect-src 'self'; object-src 'none'; base-uri 'none'; frame-ancestors 'none'";
      return html.replace("<head>", `<head>\n    <meta http-equiv="Content-Security-Policy" content="${csp}" />`);
    },
  };
}

export default defineConfig({
  plugins: [react(), cspForBuild()],
  server: {
    host: "127.0.0.1",
    port: uiPort,
    strictPort: true,
    proxy: {
      "/api": {
        target: coreUrl,
        changeOrigin: true, // Core only accepts Host: 127.0.0.1:<port>
        configure: (proxy) => {
          proxy.on("proxyReq", (proxyReq) => {
            proxyReq.setHeader("X-PBS-Token", readToken());
          });
        },
      },
    },
  },
  build: { sourcemap: true },
});
