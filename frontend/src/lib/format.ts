const BYTE_UNITS = ["B", "K", "M", "G", "T"];

/** A byte count for display, on a 1024 base: "512 B", "1.5 K", "10 K",
 *  "3.2 T". One decimal below 10, none from 10 up; whole bytes never get a
 *  decimal. The decimal mark follows the UI language ("1,5 K" in Dutch).
 *  Nothing (null, 0 or less) reads "—". */
export function fmtBytes(n: number | null | undefined, locale?: string | null): string {
  if (n == null || !Number.isFinite(n) || n <= 0) return "—";
  let value = n;
  let i = 0;
  while (value >= 1024 && i < BYTE_UNITS.length - 1) {
    value /= 1024;
    i += 1;
  }
  // Rounding may reach the next unit: 1023.7 K reads "1.0 M", not "1024 K".
  if (Math.round(value) >= 1024 && i < BYTE_UNITS.length - 1) {
    value /= 1024;
    i += 1;
  }
  const oneDecimal = i > 0 && value.toFixed(1) !== "10.0" && value < 10;
  const digits = oneDecimal ? 1 : 0;
  const shown = new Intl.NumberFormat(locale || "en", {
    minimumFractionDigits: digits,
    maximumFractionDigits: digits,
    useGrouping: false,
  }).format(oneDecimal ? value : Math.round(value));
  return `${shown} ${BYTE_UNITS[i]}`;
}

/** A count with the UI language's digit grouping ("1,234" / "1.234"). */
export function fmtNumber(n: number, locale?: string | null): string {
  return new Intl.NumberFormat(locale || "en").format(n);
}

const AGO_UNITS: Array<[Intl.RelativeTimeFormatUnit, number]> = [
  ["day", 86400],
  ["hour", 3600],
  ["minute", 60],
];

/** An ISO timestamp as relative time in the given locale ("2 hours ago"). */
export function fmtAgo(iso: string, loc: string | null | undefined): string {
  const secs = Math.round((new Date(iso).getTime() - Date.now()) / 1000);
  const rtf = new Intl.RelativeTimeFormat(loc || "en", { numeric: "auto" });
  for (const [unit, size] of AGO_UNITS) {
    if (Math.abs(secs) >= size) return rtf.format(Math.round(secs / size), unit);
  }
  return rtf.format(0, "second");
}

/** Seconds as a play position: "1:05", or "1:15:00" from an hour up. Fractions
 *  are floored; anything non-finite or negative reads "0:00". */
export function fmtDuration(seconds: number | null | undefined): string {
  if (seconds == null || !Number.isFinite(seconds) || seconds < 0) return "0:00";
  const s = Math.floor(seconds);
  const h = Math.floor(s / 3600);
  const m = Math.floor((s % 3600) / 60);
  const ss = String(s % 60).padStart(2, "0");
  return h > 0 ? `${h}:${String(m).padStart(2, "0")}:${ss}` : `${m}:${ss}`;
}

/** A calendar date in the UI language ("Jan 2, 2026" / "2 jan 2026"); "—"
 *  for nothing or an unparsable value. */
export function fmtDate(iso: string | null | undefined, locale?: string | null): string {
  if (!iso) return "—";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return "—";
  return d.toLocaleDateString(locale || "en", { dateStyle: "medium" });
}

/** A timestamp in the app's UI language (svelte-i18n `$locale`, default "en") and the browser's time zone. */
export function fmtLocalDateTime(iso: string | null, locale?: string | null): string {
  if (!iso) return "";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return iso;
  return d.toLocaleString(locale || "en", { dateStyle: "medium", timeStyle: "short" });
}
