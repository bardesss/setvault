import { api } from "./client";

export interface Webhook {
  id: string;
  name: string;
  target_url: string;
  events: string[];
  body_template: Record<string, unknown> | null;
  header_names: string[];
  secret_set: boolean;
  enabled: boolean;
  last_call_at: string | null;
  last_status_code: number | null;
  last_error: string | null;
}

export interface WebhookCreated extends Webhook {
  secret: string;
}

export interface WebhookDelivery {
  delivery_id: string;
  event: string;
  attempt: number;
  status_code: number | null;
  error: string | null;
  duration_ms: number | null;
  created_at: string;
}

export interface WebhookCreate {
  name: string;
  target_url: string;
  events: string[];
  body_template: Record<string, unknown> | null;
  headers: Record<string, string>;
  enabled: boolean;
}

/** Header merge: a string replaces, "" or null deletes, an absent name is kept. */
export interface WebhookPatch {
  enabled?: boolean;
  headers?: Record<string, string | null>;
}

const BASE = "/api/admin/webhooks";

export async function listWebhooks(): Promise<Webhook[]> {
  return (await api<{ items: Webhook[] }>(BASE)).items;
}

export function createWebhook(body: WebhookCreate): Promise<WebhookCreated> {
  return api<WebhookCreated>(BASE, { method: "POST", body: JSON.stringify(body) });
}

export function patchWebhook(id: string, body: WebhookPatch): Promise<Webhook> {
  return api<Webhook>(`${BASE}/${id}`, { method: "PATCH", body: JSON.stringify(body) });
}

export function deleteWebhook(id: string): Promise<void> {
  return api<void>(`${BASE}/${id}`, { method: "DELETE" });
}

export function testWebhook(id: string): Promise<{ status: string; delivery_id: string }> {
  return api(`${BASE}/${id}/test`, { method: "POST" });
}

export function rotateWebhookSecret(id: string): Promise<{ secret: string }> {
  return api(`${BASE}/${id}/rotate-secret`, { method: "POST" });
}

export async function listDeliveries(id: string): Promise<WebhookDelivery[]> {
  return (await api<{ items: WebhookDelivery[] }>(`${BASE}/${id}/deliveries`)).items;
}
