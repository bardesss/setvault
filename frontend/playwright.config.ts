import { defineConfig } from "@playwright/test";

const reuseExistingServer = !process.env.CI;

export default defineConfig({
  testDir: "tests",
  projects: [
    {
      name: "app",
      testIgnore: /pwa-.*\.test\.ts/,
      use: { baseURL: "http://localhost:4173" },
    },
    {
      // The PWA tests run against a production build. The dev server serves
      // source modules with Cache-Control: no-cache, which the service worker
      // (correctly) never caches, so offline behaviour there depended on the
      // browser's HTTP cache and was flaky. Production precaches /_app/.
      name: "pwa",
      testMatch: /pwa-.*\.test\.ts/,
      use: { baseURL: "http://localhost:4174" },
    },
  ],
  webServer: [
    {
      command: "npm run dev -- --port 4173",
      port: 4173,
      reuseExistingServer,
    },
    {
      command: "npm run build && npx vite preview --port 4174 --strictPort",
      port: 4174,
      env: { SETVAULT_FRONTEND_OUT: "build-e2e" },
      timeout: 180_000,
      reuseExistingServer,
    },
  ],
});
