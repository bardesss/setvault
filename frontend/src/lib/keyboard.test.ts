import { describe, expect, it } from "vitest";
import {
  hasModifier,
  isActivationTarget,
  isTypingTarget,
  shouldIgnoreShortcut,
} from "./keyboard.ts";

// vitest runs in node (no DOM), so build minimal KeyboardEvent-shaped fakes.
function el(tag: string, attrs: Record<string, string> = {}, editable = false) {
  return {
    tagName: tag.toUpperCase(),
    isContentEditable: editable,
    getAttribute: (n: string) => attrs[n] ?? null,
  };
}
function ev(
  target: unknown,
  key = "k",
  mods: Partial<Pick<KeyboardEvent, "ctrlKey" | "metaKey" | "altKey" | "defaultPrevented">> = {},
): KeyboardEvent {
  return {
    key,
    target,
    ctrlKey: false,
    metaKey: false,
    altKey: false,
    defaultPrevented: false,
    ...mods,
  } as unknown as KeyboardEvent;
}

describe("hasModifier", () => {
  it("is true for ctrl, meta, alt", () => {
    expect(hasModifier(ev(el("body"), "k", { ctrlKey: true }))).toBe(true);
    expect(hasModifier(ev(el("body"), "k", { metaKey: true }))).toBe(true);
    expect(hasModifier(ev(el("body"), "k", { altKey: true }))).toBe(true);
  });
  it("is false for plain keys", () => {
    expect(hasModifier(ev(el("body")))).toBe(false);
  });
});

describe("isTypingTarget", () => {
  it("is true for input, textarea, select and contenteditable", () => {
    expect(isTypingTarget(ev(el("input")))).toBe(true);
    expect(isTypingTarget(ev(el("textarea")))).toBe(true);
    expect(isTypingTarget(ev(el("select")))).toBe(true);
    expect(isTypingTarget(ev(el("div", {}, true)))).toBe(true);
  });
  it("is true for role textbox, combobox, slider, listbox", () => {
    for (const role of ["textbox", "combobox", "slider", "listbox"]) {
      expect(isTypingTarget(ev(el("div", { role })))).toBe(true);
    }
  });
  it("is false for body and button", () => {
    expect(isTypingTarget(ev(el("body")))).toBe(false);
    expect(isTypingTarget(ev(el("button")))).toBe(false);
  });
  it("is false when there is no element target", () => {
    expect(isTypingTarget(ev(null))).toBe(false);
  });
});

describe("isActivationTarget", () => {
  it("is true for buttons, links, summary and button-like roles", () => {
    expect(isActivationTarget(ev(el("button")))).toBe(true);
    expect(isActivationTarget(ev(el("a", { href: "/x" })))).toBe(true);
    expect(isActivationTarget(ev(el("summary")))).toBe(true);
    expect(isActivationTarget(ev(el("div", { role: "button" })))).toBe(true);
    expect(isActivationTarget(ev(el("div", { role: "radio" })))).toBe(true);
  });
  it("is false for body and inputs", () => {
    expect(isActivationTarget(ev(el("body")))).toBe(false);
    expect(isActivationTarget(ev(el("input")))).toBe(false);
  });
});

describe("shouldIgnoreShortcut", () => {
  it("never ignores a plain key on body", () => {
    expect(shouldIgnoreShortcut(ev(el("body"), "k"), "k")).toBe(false);
    expect(shouldIgnoreShortcut(ev(el("body"), " "), " ")).toBe(false);
  });
  it("ignores modified keys", () => {
    expect(shouldIgnoreShortcut(ev(el("body"), "k", { ctrlKey: true }), "k")).toBe(true);
    expect(shouldIgnoreShortcut(ev(el("body"), "k", { metaKey: true }), "k")).toBe(true);
    expect(shouldIgnoreShortcut(ev(el("body"), "b", { altKey: true }), "b")).toBe(true);
  });
  it("ignores typing targets and defaultPrevented", () => {
    expect(shouldIgnoreShortcut(ev(el("input"), "k"), "k")).toBe(true);
    expect(shouldIgnoreShortcut(ev(el("body"), "k", { defaultPrevented: true }), "k")).toBe(true);
  });
  it("space and enter ignore activation targets, letters do not", () => {
    expect(shouldIgnoreShortcut(ev(el("button"), " "), " ")).toBe(true);
    expect(shouldIgnoreShortcut(ev(el("button"), "Enter"), "Enter")).toBe(true);
    expect(shouldIgnoreShortcut(ev(el("button"), "k"), "k")).toBe(false);
  });
  it("arrows ignore select and slider/tab/radio/listbox roles", () => {
    expect(shouldIgnoreShortcut(ev(el("select"), "ArrowLeft"), "ArrowLeft")).toBe(true);
    for (const role of ["slider", "tab", "radio", "listbox"]) {
      expect(shouldIgnoreShortcut(ev(el("div", { role }), "ArrowRight"), "ArrowRight")).toBe(true);
    }
    expect(shouldIgnoreShortcut(ev(el("body"), "ArrowLeft"), "ArrowLeft")).toBe(false);
  });
});
