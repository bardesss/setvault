const BYTE_UNITS = ["B", "K", "M", "G", "T"];

/** A byte count for display, on a 1024 base: "512 B", "1.5 K", "10 K",
 *  "3.2 T". One decimal below 10, none from 10 up; whole bytes never get a
 *  decimal. Nothing (null, 0 or less) reads "—". */
export function fmtBytes(n: number | null | undefined): string {
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
  return `${oneDecimal ? value.toFixed(1) : Math.round(value)} ${BYTE_UNITS[i]}`;
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
