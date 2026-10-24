/**
 * A readable message from an API error `detail`. FastAPI sends a string, a
 * list of strings (template validation) or pydantic's list of `{loc, msg}`.
 */
export function formatDetail(detail: unknown): string {
  if (typeof detail === "string") return detail;
  if (Array.isArray(detail)) {
    return detail
      .map((d: unknown) => {
        if (typeof d === "string") return d;
        if (d && typeof d === "object") {
          const { loc, msg } = d as { loc?: unknown[]; msg?: unknown };
          const path = Array.isArray(loc) ? loc.filter((p) => p !== "body") : [];
          const field = path.length > 0 ? `${path[path.length - 1]}: ` : "";
          return `${field}${typeof msg === "string" ? msg : JSON.stringify(d)}`;
        }
        return String(d);
      })
      .join("; ");
  }
  if (detail && typeof detail === "object") {
    const msg = (detail as { msg?: unknown }).msg;
    return typeof msg === "string" ? msg : JSON.stringify(detail);
  }
  return String(detail);
}

/** A readable message for anything thrown by `api()`: the API detail without the status prefix. */
export function errorMessage(e: unknown): string {
  if (e instanceof Error) {
    const detail = (e as { detail?: unknown }).detail;
    return typeof detail === "string" ? detail : e.message;
  }
  return String(e);
}
