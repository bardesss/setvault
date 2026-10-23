import { writable, type Readable } from "svelte/store";

export interface Toast {
  id: number;
  kind: "success" | "error";
  message: string;
}

const SUCCESS_MS = 4000;

const store = writable<Toast[]>([]);
let nextId = 1;

function push(kind: Toast["kind"], message: string): number {
  const id = nextId++;
  store.update((list) => [...list, { id, kind, message }]);
  if (kind === "success") setTimeout(() => dismiss(id), SUCCESS_MS);
  return id;
}

function dismiss(id: number): void {
  store.update((list) => list.filter((t) => t.id !== id));
}

export const toasts: Readable<Toast[]> = { subscribe: store.subscribe };

export const toast = {
  success: (message: string) => push("success", message),
  error: (message: string) => push("error", message),
  dismiss,
};
