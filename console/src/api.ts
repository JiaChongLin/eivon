export type ApiError = { error?: { code?: string; message?: string; details?: unknown } };
let csrf = "";
export function setCsrf(value: string) { csrf = value; }
export async function api<T>(path: string, init: RequestInit = {}): Promise<T> {
  const headers = new Headers(init.headers);
  if (init.body && !headers.has("content-type")) headers.set("content-type", "application/json");
  if (csrf) headers.set("x-csrf-token", csrf);
  const response = await fetch(`/api/v1${path}`, { ...init, headers, credentials: "include" });
  const value = await response.json().catch(() => ({}));
  if (!response.ok) throw new Error((value as ApiError).error?.message || `Request failed (${response.status})`);
  return value as T;
}
export type Resource = { id: string; kind: string; name: string; slug: string; draft: Record<string, unknown>; revision: number; latest_version: number; active_version: number | null; archived: boolean; updated_at: number };
export type Run = { id: string; resource_id: string; resource_version: number; status: string; output: Record<string, unknown>; error?: string; event_sequence: number; created_at: number; finished_at?: number };
