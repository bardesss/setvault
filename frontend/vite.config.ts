/// <reference types="vitest/config" />
import adapter from "@sveltejs/adapter-static";
import { sveltekit } from "@sveltejs/kit/vite";
import { vitePreprocess } from "@sveltejs/vite-plugin-svelte";
import { defineConfig } from "vite";

// The e2e PWA tests build into a throwaway dir so they don't clobber the
// tracked placeholder index.html in the backend's static folder.
const pages = process.env.SETVAULT_FRONTEND_OUT ?? "../apps/web/src/setvault_web/static";

export default defineConfig({
  plugins: [
    // SvelteKit 3 takes its config as plugin options; svelte.config.js is gone.
    sveltekit({
      preprocess: vitePreprocess(),
      adapter: adapter({ pages, fallback: "index.html" }),
      // Kit 3 polls for a new app version hourly by default; Kit 2 never did.
      // Keep the Kit 2 behaviour: updates arrive through the service worker.
      version: { pollInterval: 0 },
    }),
  ],
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
