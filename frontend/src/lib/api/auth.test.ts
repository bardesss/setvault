import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";

const api = vi.fn();
vi.mock("./client", () => ({ api: (...a: unknown[]) => api(...a) }));
vi.mock("../stores/offline", () => ({ clearScopedCaches: async () => undefined }));

beforeEach(() => { api.mockReset().mockResolvedValue(undefined); });
afterEach(() => { vi.unstubAllGlobals(); });

describe("logout", () => {
  it("removes the stored play queue", async () => {
    const removeItem = vi.fn();
    vi.stubGlobal("localStorage", { removeItem });
    const { logout } = await import("./auth");
    await logout();
    expect(removeItem).toHaveBeenCalledWith("setvault.playQueue");
  });

  it("still resolves when localStorage throws", async () => {
    vi.stubGlobal("localStorage", { removeItem: () => { throw new Error("denied"); } });
    const { logout } = await import("./auth");
    await expect(logout()).resolves.toBeUndefined();
  });

  it("purges the queue even when the request fails", async () => {
    api.mockRejectedValue(new Error("offline"));
    const removeItem = vi.fn();
    vi.stubGlobal("localStorage", { removeItem });
    const { logout } = await import("./auth");
    await expect(logout()).rejects.toThrow("offline");
    expect(removeItem).toHaveBeenCalledWith("setvault.playQueue");
  });
});
