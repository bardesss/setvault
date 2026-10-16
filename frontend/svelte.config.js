import adapter from "@sveltejs/adapter-static";
import { vitePreprocess } from "@sveltejs/vite-plugin-svelte";

// The e2e PWA tests build into a throwaway dir so they don't clobber the
// tracked placeholder index.html in the backend's static folder.
const pages = process.env.SETVAULT_FRONTEND_OUT ?? "../apps/web/src/setvault_web/static";

export default {
  preprocess: vitePreprocess(),
  kit: {
    adapter: adapter({ pages, fallback: "index.html" }),
    alias: { $lib: "src/lib" },
  },
};
