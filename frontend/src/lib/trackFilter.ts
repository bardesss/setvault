const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;

/** Whether a ?track= value is shaped like a track id (the API 422s otherwise). */
export function isTrackId(value: string): boolean {
  return UUID.test(value);
}

/** A rejected track filter (malformed id) is an empty result, not an error page. */
export function isBadTrackFilter(status: number, track: string): boolean {
  return status === 422 && track !== "";
}
