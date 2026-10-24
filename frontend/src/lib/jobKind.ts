/** i18n key for a recorded job kind such as "email.send_email_job". */
export function jobKindKey(kind: string): string {
  return `admin.jobs.kinds.${kind.replace(/[^A-Za-z0-9_]/g, "_")}`;
}

type Translate = (key: string, opts?: { default?: string }) => string;

/** A readable label for a job kind; the raw kind when no label exists. */
export function jobKindLabel(kind: string, t: Translate): string {
  return t(jobKindKey(kind), { default: kind });
}
