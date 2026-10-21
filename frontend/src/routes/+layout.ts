import { redirect } from "@sveltejs/kit";
import { isPublicRoute } from "#lib/auth/routes.ts";
import type { LayoutLoad } from "./$types";

// Pure client-side SPA: the bundled image serves the static build via FastAPI,
// so there is no SvelteKit server to run server `load`s. ssr=false here applies
// app-wide; universal loads fetch /api directly from the browser (the session
// cookie rides along same-origin).
export const ssr = false;

// Public routes that can never be the first-run target (no embeds/invites/
// resets exist on an empty install), so they skip the setup-status COUNT.
const SETUP_GATE_SKIP_PREFIXES = ["/embed/", "/invite/", "/reset/"];

export const load: LayoutLoad = async ({ fetch, url }) => {
  // First-run gate: with zero users, force the setup wizard; once setup is
  // done, keep /setup locked. Cheap COUNT query — skipped on public routes.
  if (!SETUP_GATE_SKIP_PREFIXES.some((p) => url.pathname.startsWith(p))) {
    const statusRes = await fetch("/api/setup/status");
    const needsSetup = statusRes.ok
      ? (await statusRes.json()).needs_setup === true
      : false;
    if (needsSetup && url.pathname !== "/setup") {
      throw redirect(303, "/setup");
    }
    if (!needsSetup && url.pathname === "/setup") {
      throw redirect(303, "/login");
    }
  }

  // No httpOnly cookie access on the client — ask the API. 401 ⇒ logged out.
  // (When single-user auto-login is enabled, /api/auth/me establishes the
  // session server-side and returns the user, so this won't 401.)
  const response = await fetch("/api/auth/me");
  if (!response.ok) {
    // Logged out on a protected route → send them to the login page instead of
    // rendering a bare logged-out shell.
    if (!isPublicRoute(url.pathname)) {
      throw redirect(303, "/login");
    }
    return { user: null };
  }
  return { user: await response.json() };
};
