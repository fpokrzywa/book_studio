import react from "@vitejs/plugin-react";
import { defineConfig, type Plugin } from "vite";

const coreUrl = process.env.PBS_CORE_URL ?? "http://127.0.0.1:8765";
const uiPort = Number(process.env.PBS_UI_PORT ?? 5173);

/** Strict CSP for production builds (dev needs inline scripts for React Fast Refresh). */
function cspForBuild(): Plugin {
  return {
    name: "pbs-csp",
    apply: "build",
    transformIndexHtml(html) {
      const csp =
        "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data: blob:; " +
        "media-src 'self' blob:; font-src 'self'; connect-src 'self'; object-src 'none'; base-uri 'none'; " +
        "form-action 'self'"; // Core also sends this policy (plus frame-ancestors) as a header
      return html.replace(
        "<head>",
        `<head>\n    <meta http-equiv="Content-Security-Policy" content="${csp}" />`,
      );
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
        // Core only accepts Host: 127.0.0.1:<port>. The browser's sign-in cookie and CSRF header
        // pass through unchanged; there is no shared secret in the proxy any more.
        changeOrigin: true,
      },
    },
  },
  build: { sourcemap: true },
});
