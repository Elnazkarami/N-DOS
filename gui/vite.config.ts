// A plain single-page build. NDOS serves the result from a local Python
// process, so there is nothing to render on a server and nothing to deploy:
// the output is a folder of files that ship inside the Python package.
import { tanstackRouter } from "@tanstack/router-plugin/vite";
import tailwindcss from "@tailwindcss/vite";
import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";
import tsConfigPaths from "vite-tsconfig-paths";

// `npm run dev` serves the page, but the page is useless without the Python
// server behind it: it has no way to read a disk and no token to ask with.
// So the dev server forwards /api to a running `ndos gui` and injects that
// server's token, the way the Python server does for the built page.
//
//     ndos gui --no-browser                 # prints a URL with a token in it
//     NDOS_TOKEN=<that token> npm run dev
//
// Without NDOS_TOKEN the page still loads and still renders; it just reports
// that it is not being served by N-DOS, which is the right answer.
const NDOS_PORT = Number(process.env["NDOS_PORT"] ?? 7373);
const NDOS_TOKEN = process.env["NDOS_TOKEN"] ?? "";

function injectDevToken() {
  return {
    name: "ndos-dev-token",
    apply: "serve" as const,
    transformIndexHtml(html: string) {
      if (!NDOS_TOKEN) return html;
      return html.replace(
        "</head>",
        `<script>window.__NDOS__={token:${JSON.stringify(NDOS_TOKEN)},version:"dev"};</script></head>`,
      );
    },
  };
}

export default defineConfig({
  // Relative, so the built files work from any path the server mounts them at.
  base: "./",
  server: {
    proxy: {
      "/api": { target: `http://127.0.0.1:${NDOS_PORT}` },
    },
  },
  plugins: [
    tanstackRouter({ target: "react", autoCodeSplitting: true }),
    react(),
    tailwindcss(),
    tsConfigPaths(),
    injectDevToken(),
  ],
  build: {
    outDir: "dist",
    emptyOutDir: true,
    // One bundle keeps the package small and the server simple; this is a
    // local tool, not a site where first paint over a network matters.
    chunkSizeWarningLimit: 1500,
  },
});
