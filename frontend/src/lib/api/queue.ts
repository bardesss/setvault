import { api } from "./client";

export interface QueueOut {
  slugs: string[];
  index: number;
  updated_at: string | null;
}

export interface QueuePutBody {
  slugs: string[];
  index: number;
  base_updated_at: string | null;
}

export interface QueuePutResult {
  updated_at: string;
  overwrote_newer: boolean;
}

export const getQueue = () => api<QueueOut>("/api/me/queue");

export const putQueue = (body: QueuePutBody, init: RequestInit = {}) =>
  api<QueuePutResult>("/api/me/queue", { ...init, method: "PUT", body: JSON.stringify(body) });
