import { formatDetail } from "./errors";

const BASE = "";

function getCookie(name: string): string | null {
  if (typeof document === "undefined") return null;
  const m = document.cookie.match(new RegExp("(?:^|; )" + name + "=([^;]*)"));
  return m ? decodeURIComponent(m[1]) : null;
}

export class ApiError extends Error {
  constructor(
    public status: number,
    public detail: string,
  ) {
    super(`${status}: ${detail}`);
  }
}

export async function api<T = unknown>(
  path: string,
  init: RequestInit = {},
): Promise<T> {
  const method = (init.method ?? "GET").toUpperCase();
  const headers = new Headers(init.headers);
  if (method !== "GET" && method !== "HEAD") {
    const csrf = getCookie("csrf_token");
    if (csrf) headers.set("X-CSRF-Token", csrf);
  }
  if (init.body && !headers.has("Content-Type")) {
    headers.set("Content-Type", "application/json");
  }
  const response = await fetch(BASE + path, {
    ...init,
    headers,
    credentials: "same-origin",
  });
  if (!response.ok) {
    let detail = response.statusText;
    try {
      // detail may be a string, a string list or pydantic's {loc,msg} list.
      detail = formatDetail((await response.json()).detail ?? detail);
    } catch {
      /* noop */
    }
    throw new ApiError(response.status, detail);
  }
  if (response.status === 204) return undefined as T;
  return (await response.json()) as T;
}
