import { afterEach, describe, expect, it, vi } from "vitest";
import { copyText } from "./clipboard.ts";

function stubDom(opts: { clipboard?: unknown; exec?: () => boolean }) {
  const textarea: Record<string, unknown> = {
    style: {},
    focus: vi.fn(),
    select: vi.fn(),
    setAttribute: vi.fn(),
  };
  const doc = {
    createElement: vi.fn(() => textarea),
    body: { appendChild: vi.fn(), removeChild: vi.fn() },
    execCommand: vi.fn(opts.exec ?? (() => true)),
  };
  vi.stubGlobal("navigator", { clipboard: opts.clipboard });
  vi.stubGlobal("document", doc);
  return doc;
}

afterEach(() => vi.unstubAllGlobals());

describe("copyText", () => {
  it("uses navigator.clipboard when present", async () => {
    const writeText = vi.fn().mockResolvedValue(undefined);
    const doc = stubDom({ clipboard: { writeText } });
    expect(await copyText("hi")).toBe(true);
    expect(writeText).toHaveBeenCalledWith("hi");
    expect(doc.execCommand).not.toHaveBeenCalled();
  });

  it("falls back to execCommand when clipboard is missing", async () => {
    const doc = stubDom({ clipboard: undefined });
    expect(await copyText("hi")).toBe(true);
    expect(doc.execCommand).toHaveBeenCalledWith("copy");
    expect(doc.body.removeChild).toHaveBeenCalled();
  });

  it("returns false when both fail", async () => {
    stubDom({
      clipboard: { writeText: vi.fn().mockRejectedValue(new Error("no")) },
      exec: () => false,
    });
    expect(await copyText("hi")).toBe(false);
  });
});
