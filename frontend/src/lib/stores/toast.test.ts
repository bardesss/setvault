import { get } from "svelte/store";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { toast, toasts } from "./toast.ts";

describe("toast store", () => {
  beforeEach(() => {
    vi.useFakeTimers();
  });
  afterEach(() => {
    for (const t of get(toasts)) toast.dismiss(t.id);
    vi.useRealTimers();
  });

  it("auto-dismisses success after 4000 ms", () => {
    toast.success("saved");
    expect(get(toasts)).toHaveLength(1);
    expect(get(toasts)[0]).toMatchObject({ kind: "success", message: "saved" });
    vi.advanceTimersByTime(3999);
    expect(get(toasts)).toHaveLength(1);
    vi.advanceTimersByTime(1);
    expect(get(toasts)).toHaveLength(0);
  });

  it("keeps errors until dismissed", () => {
    toast.error("boom");
    vi.advanceTimersByTime(60_000);
    const list = get(toasts);
    expect(list).toHaveLength(1);
    expect(list[0].kind).toBe("error");
    toast.dismiss(list[0].id);
    expect(get(toasts)).toHaveLength(0);
  });

  it("dismiss removes only the given toast", () => {
    toast.error("a");
    toast.error("b");
    const [a, b] = get(toasts);
    toast.dismiss(a.id);
    expect(get(toasts).map((t) => t.id)).toEqual([b.id]);
  });
});
