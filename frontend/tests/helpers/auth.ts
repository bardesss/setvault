import type { APIRequestContext, Page } from "@playwright/test";

const API_BASE = process.env.SETVAULT_API_BASE ?? "http://localhost:1970";

interface SeedResponse {
  admin: { email: string; password: string };
  set: { slug: string };
}

/**
 * Hits the dev-seed endpoint (gated by SETVAULT_DEV_SEED on the backend) to
 * idempotently provision an admin user + published LiveSet with slug
 * "seeded-set", then logs the Playwright page in as that admin so the page's
 * cookie jar has a valid session for the frontend.
 *
 * Returns the seed payload (slug, admin credentials) for any caller that
 * wants to assert on them.
 */
export async function loginAs(
  page: Page,
  request: APIRequestContext,
): Promise<SeedResponse> {
  const seedResponse = await request.post(`${API_BASE}/api/dev/seed-e2e`);
  if (!seedResponse.ok()) {
    throw new Error(
      `dev seed endpoint failed (${seedResponse.status()}): is the backend running with SETVAULT_DEV_SEED=1?`,
    );
  }
  const seed = (await seedResponse.json()) as SeedResponse;

  // Log in through the frontend dev server so cookies are scoped to the page origin.
  const loginResponse = await page.request.post("/api/auth/login", {
    data: { email: seed.admin.email, password: seed.admin.password },
    headers: { "Content-Type": "application/json" },
  });
  if (!loginResponse.ok()) {
    throw new Error(`login failed (${loginResponse.status()})`);
  }
  // Playwright stores Set-Cookie automatically; nothing else needed.
  return seed;
}

/**
 * Creates a throwaway member through the invite flow (as the seed admin) and
 * leaves the page logged in as that member. Never mutates the admin's data.
 */
export async function createMember(
  page: Page,
  request: APIRequestContext,
): Promise<{ email: string; password: string }> {
  await loginAs(page, request);
  const cookies = await page.context().cookies();
  const csrf = cookies.find((c) => c.name === "csrf_token")?.value ?? "";

  const suffix = `${Date.now().toString(36)}${Math.random().toString(36).slice(2, 7)}`;
  const email = `member-${suffix}@example.test`;
  const password = "initial-password-55";
  const invite = await page.request.post("/api/invites", {
    data: { email, role: "user" },
    headers: { "X-CSRF-Token": csrf },
  });
  if (!invite.ok()) throw new Error(`invite failed (${invite.status()})`);
  const token = ((await invite.json()) as { invite_link: string }).invite_link.split("/").pop();

  // Redeeming logs the page in as the new user (replaces the admin session).
  const redeem = await page.request.post(`/api/invites/${token}/redeem`, {
    data: { username: `m${suffix}`, display_name: "E2E Member", password },
  });
  if (!redeem.ok()) throw new Error(`redeem failed (${redeem.status()})`);
  return { email, password };
}
