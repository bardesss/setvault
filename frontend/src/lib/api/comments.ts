import { api } from "./client";

export interface CommentAuthor {
  id: string;
  username: string;
  display_name: string | null;
}

export interface Comment {
  id: string;
  parent_id: string | null;
  position_seconds: number | null;
  body_html: string;
  body_md: string;
  author: CommentAuthor;
  mentions: CommentAuthor[];
  edited_at: string | null;
  deleted_at: string | null;
  created_at: string;
}

export interface CommentsList {
  items: Comment[];
  total: number;
}

export const listComments = (slug: string) =>
  api<CommentsList>(`/api/sets/${encodeURIComponent(slug)}/comments`);

export const postComment = (
  slug: string,
  body: { body: string; parent_id?: string | null; position_seconds?: number | null },
) =>
  api<Comment>(`/api/sets/${encodeURIComponent(slug)}/comments`, {
    method: "POST",
    body: JSON.stringify(body),
  });

export const deleteComment = (id: string) =>
  api<void>(`/api/comments/${id}`, { method: "DELETE" });
