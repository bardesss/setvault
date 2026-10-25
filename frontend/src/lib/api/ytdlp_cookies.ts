import { api } from "./client";

/** The YouTube cookies yt-dlp sends; the contents never leave the server. */
export interface YtdlpCookiesStatus {
  set: boolean;
  uploaded_at: string | null;
  youtube_cookies: number;
}

const URL = "/api/admin/ytdlp-cookies";

export function getYtdlpCookies(): Promise<YtdlpCookiesStatus> {
  return api<YtdlpCookiesStatus>(URL);
}

/** Upload a Netscape cookies.txt as the raw request body (admin only). */
export function uploadYtdlpCookies(text: string): Promise<YtdlpCookiesStatus> {
  return api<YtdlpCookiesStatus>(URL, {
    method: "PUT",
    body: text,
    headers: { "Content-Type": "text/plain" },
  });
}

export function removeYtdlpCookies(): Promise<void> {
  return api<void>(URL, { method: "DELETE" });
}
