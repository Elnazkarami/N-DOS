// A plain single-page build. NDOS serves the result from a local Python
// process, so there is nothing to render on a server and nothing to deploy:
// the output is a folder of files that ship inside the Python package.
import { tanstackRouter } from "@tanstack/router-plugin/vite";
import tailwindcss from "@tailwindcss/vite";
import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";
import tsConfigPaths from "vite-tsconfig-paths";

export default defineConfig({
  // Relative, so the built files work from any path the server mounts them at.
  base: "./",
  plugins: [
    tanstackRouter({ target: "react", autoCodeSplitting: true }),
    react(),
    tailwindcss(),
    tsConfigPaths(),
  ],
  build: {
    outDir: "dist",
    emptyOutDir: true,
    // One bundle keeps the package small and the server simple; this is a
    // local tool, not a site where first paint over a network matters.
    chunkSizeWarningLimit: 1500,
  },
});
