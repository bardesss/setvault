// Shared guards for global (window-level) keyboard shortcuts. They duck-type
// the event target so they also work outside a real DOM (unit tests).

type Tgt = {
  tagName?: string;
  isContentEditable?: boolean;
  getAttribute?: (name: string) => string | null;
};

function target(e: KeyboardEvent): Tgt | null {
  const path = typeof e.composedPath === "function" ? e.composedPath() : [];
  const t = (path[0] ?? e.target) as Tgt | null;
  return t && typeof t.tagName === "string" ? t : null;
}

function role(t: Tgt): string {
  return (t.getAttribute?.("role") ?? "").toLowerCase();
}

export function hasModifier(e: KeyboardEvent): boolean {
  return e.ctrlKey || e.metaKey || e.altKey;
}

/** Focus is in something the user types into (or picks from): letters are text, not shortcuts. */
export function isTypingTarget(e: KeyboardEvent): boolean {
  const t = target(e);
  if (!t) return false;
  const tag = t.tagName!.toUpperCase();
  if (tag === "INPUT" || tag === "TEXTAREA" || tag === "SELECT" || t.isContentEditable === true) return true;
  return ["textbox", "combobox", "slider", "listbox"].includes(role(t));
}

/** Focus is on a control that Space/Enter activates natively. */
export function isActivationTarget(e: KeyboardEvent): boolean {
  const t = target(e);
  if (!t) return false;
  const tag = t.tagName!.toUpperCase();
  if (tag === "BUTTON" || tag === "SUMMARY" || tag === "A") return true;
  return ["button", "link", "menuitem", "checkbox", "switch", "tab", "radio", "option"].includes(role(t));
}

const ARROWS = new Set(["ArrowLeft", "ArrowRight", "ArrowUp", "ArrowDown"]);
const ARROW_ROLES = new Set(["slider", "tab", "radio", "listbox"]);

export function shouldIgnoreShortcut(e: KeyboardEvent, key: string): boolean {
  if (e.defaultPrevented || hasModifier(e) || isTypingTarget(e)) return true;
  if ((key === " " || key === "Enter") && isActivationTarget(e)) return true;
  if (ARROWS.has(key)) {
    const t = target(e);
    if (t && (t.tagName!.toUpperCase() === "SELECT" || ARROW_ROLES.has(role(t)))) return true;
  }
  return false;
}
