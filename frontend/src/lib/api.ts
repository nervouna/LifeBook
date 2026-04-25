const BASE = "/api";

async function request<T>(path: string, options?: RequestInit): Promise<T> {
  const res = await fetch(`${BASE}${path}`, {
    headers: { "Content-Type": "application/json" },
    ...options,
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({ error: res.statusText }));
    throw new Error(err.error || err.detail || res.statusText);
  }
  return res.json();
}

export const api = {
  listNotes: (params?: Record<string, string>) =>
    request<NoteListResponse>(`/notes?${new URLSearchParams(params || {})}`),
  getNote: (path: string) => request<NoteDetail>(`/notes/${path}`),
  updateNote: (path: string, body: Partial<NoteUpdate>) =>
    request<NoteDetail>(`/notes/${path}`, { method: "PUT", body: JSON.stringify(body) }),
  deleteNote: (path: string) => request<{ ok: boolean }>(`/notes/${path}`, { method: "DELETE" }),
  listInbox: (params?: Record<string, string>) =>
    request<InboxListResponse>(`/inbox?${new URLSearchParams(params || {})}`),
  ingest: (body: { url_or_text: string; source_type?: string; title?: string }) =>
    request<{ path: string }>("/inbox", { method: "POST", body: JSON.stringify(body) }),
  search: (query: string, limit = 10) =>
    request<SearchResponse>("/search", { method: "POST", body: JSON.stringify({ query, limit }) }),
  writerStatus: () => request<WriterStatus>("/writer/status"),
  writerStart: (idea: string) =>
    request<WriterChatResponse>("/writer/start", { method: "POST", body: JSON.stringify({ idea }) }),
  writerChat: (message: string) =>
    request<WriterChatResponse>("/writer/chat", { method: "POST", body: JSON.stringify({ message }) }),
  writerPublish: (force = false) =>
    request<{ reply: string }>(`/writer/publish?force=${force}`, { method: "POST" }),
  doctor: () => request<DoctorResponse>("/system/doctor"),
  stats: () => request<StatsResponse>("/system/stats"),
  categories: () => request<CategoryListResponse>("/categories"),
  tags: () => request<TagListResponse>("/tags"),
  generatePodcast: (notePath: string) =>
    request<{ path: string }>("/podcast/generate", { method: "POST", body: JSON.stringify({ note_path: notePath }) }),
};

export type NoteListItem = { path: string; title: string; category: string; tags: string[]; created: string; status: string; summary: string };
export type NoteListResponse = { items: NoteListItem[]; total: number; page: number; per_page: number };
export type NoteDetail = { path: string; title: string; category: string; tags: string[]; created: string; body: string; metadata: Record<string, unknown> };
export type NoteUpdate = { title?: string; tags?: string[]; category?: string; body?: string };
export type InboxItem = { path: string; title: string; status: string; source_type: string; source: string; created: string; error: string | null };
export type InboxListResponse = { items: InboxItem[]; total: number };
export type SearchResultItem = { path: string; title: string; score: number; preview: string };
export type SearchResponse = { results: SearchResultItem[]; query: string };
export type WriterStatus = { active: boolean; stage: string | null; title: string | null };
export type WriterChatResponse = { reply: string; stage: string | null };
export type DoctorResponse = { checks: { name: string; ok: boolean }[] };
export type StatsResponse = { topic_count: number; inbox_count: number; categories: string[]; index_status: string };
export type CategoryListResponse = { categories: string[] };
export type TagListResponse = { tags: string[] };
