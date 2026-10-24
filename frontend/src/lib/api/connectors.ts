import { api } from "./client";

export type SmtpEncryption = "starttls" | "ssl" | "none";

export interface SmtpConfig {
  host: string;
  port: number;
  encryption: SmtpEncryption;
  username: string | null;
  password_set: boolean;
  from_email: string;
  from_name: string;
  reply_to: string | null;
}

export interface Connector {
  id: string;
  kind: string;
  name: string;
  enabled: boolean;
  scope_filter: Record<string, unknown>;
  config: SmtpConfig;
}

/** Write shape of the SMTP config; a missing or empty password keeps the stored one. */
export interface SmtpConfigWrite {
  host: string;
  port: number;
  encryption: SmtpEncryption;
  username: string | null;
  password?: string;
  from_email: string;
  from_name: string;
  reply_to: string | null;
}

export interface TestSendResult {
  accepted: boolean;
  dry_run: boolean;
  error: string | null;
}

export async function listConnectors(): Promise<Connector[]> {
  return (await api<{ items: Connector[] }>("/api/connectors")).items;
}

export function createSmtpConnector(
  name: string,
  config: SmtpConfigWrite,
  enabled: boolean,
): Promise<Connector> {
  return api<Connector>("/api/connectors", {
    method: "POST",
    body: JSON.stringify({ kind: "smtp", name, config, enabled }),
  });
}

export function patchConnector(
  id: string,
  body: { name?: string; enabled?: boolean; config?: Partial<SmtpConfigWrite> },
): Promise<Connector> {
  return api<Connector>(`/api/connectors/${id}`, { method: "PATCH", body: JSON.stringify(body) });
}

export function deleteConnector(id: string): Promise<void> {
  return api<void>(`/api/connectors/${id}`, { method: "DELETE" });
}

export function testSend(id: string, to: string, dryRun: boolean): Promise<TestSendResult> {
  return api<TestSendResult>(`/api/connectors/${id}/test-send`, {
    method: "POST",
    body: JSON.stringify({ to, dry_run: dryRun }),
  });
}
