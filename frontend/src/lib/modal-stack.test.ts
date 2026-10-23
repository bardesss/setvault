import { describe, expect, it } from "vitest";
import { isTopModal, pushModal, removeModal } from "./modal-stack.ts";

describe("modal stack", () => {
  it("only the most recently opened modal is on top", () => {
    const a = Symbol("a");
    const b = Symbol("b");
    expect(isTopModal(a)).toBe(false);
    pushModal(a);
    expect(isTopModal(a)).toBe(true);
    pushModal(b);
    expect(isTopModal(a)).toBe(false);
    expect(isTopModal(b)).toBe(true);
    removeModal(b);
    expect(isTopModal(a)).toBe(true);
    removeModal(a);
    expect(isTopModal(a)).toBe(false);
  });

  it("push is idempotent and removing an unknown id is a no-op", () => {
    const a = Symbol("a");
    pushModal(a);
    pushModal(a);
    removeModal(Symbol("x"));
    removeModal(a);
    expect(isTopModal(a)).toBe(false);
  });
});
