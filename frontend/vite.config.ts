/// <reference types="vitest" />
import { sveltekit } from "@sveltejs/kit/vite";
import { defineConfig } from "vite";

export default defineConfig({
  plugins: [sveltekit()],
  server: {
    proxy: { "/api": "http://localhost:1970", "/uploads": "http://localhost:1080" },
  },
  // Pre-bundle runtime deps at dev-server start. Otherwise a cold server
  // discovers them on first use (e.g. wavesurfer.js on the set page), then
  // re-optimizes and force-reloads mid-page with new ?v= module URLs. That
  // made e2e flaky on cold CI runs, notably the PWA offline reload test,
  // whose cached module URLs went stale.
  optimizeDeps: {
    include: ["svelte-i18n", "wavesurfer.js", "tus-js-client"],
  },
  test: { environment: "node", exclude: ["tests/**", "node_modules/**"] },
});
