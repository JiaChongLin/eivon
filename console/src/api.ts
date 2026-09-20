export type ApiError = { error?: { code?: string; message?: string; details?: unknown } };
export type Identity = { user: { id: string; name: string; email: string }; workspace_id: string; role: string; permissions: string[]; workspaces: { id: string; name: string; role: string }[]; csrf_token?: string };
let csrf = "";
let workspace = "";
let generation = 0;
const pending = new Set<AbortController>();
export function setCsrf(value: string) { csrf = value; }
export function setWorkspace(value: string) {
  if (workspace === value) return;
  workspace = value; cancelPendingRequests();
}
export function cancelPendingRequests() {
  generation++;
  for (const controller of pending) controller.abort();
  pending.clear();
}
export class ApiRequestError extends Error {
  constructor(message: string, public status: number, public code?: string) { super(message); }
}
async function request<T>(path: string, init: RequestInit, read: (response: Response) => Promise<T>): Promise<T> {
  const epoch = generation;
  const controller = new AbortController();
  pending.add(controller);
  const headers = new Headers(init.headers);
  if (init.body && !headers.has("content-type")) headers.set("content-type", "application/json");
  if (csrf) headers.set("x-csrf-token", csrf);
  if (workspace && !headers.has("x-eivon-workspace")) headers.set("x-eivon-workspace", workspace);
  const abort = () => controller.abort();
  init.signal?.addEventListener("abort", abort, { once: true });
  if (init.signal?.aborted) controller.abort();
  try {
    const response = await fetch(`/api/v1${path}`, { ...init, headers, credentials: "include", signal: controller.signal });
    if (!response.ok) {
      const value: ApiError = await response.json().catch(() => ({}));
      throw new ApiRequestError(value.error?.message || `Request failed (${response.status})`, response.status, value.error?.code);
    }
    const value = await read(response);
    if (epoch !== generation || controller.signal.aborted) throw new DOMException("Workspace changed or request cancelled", "AbortError");
    return value;
  } finally { pending.delete(controller); init.signal?.removeEventListener("abort", abort); }
}
export function api<T>(path: string, init: RequestInit = {}): Promise<T> {
  return request(path, init, (response) => response.json().catch(() => ({})));
}
export async function downloadArtifact(id: string, name: string) {
  const blob = await request(`/artifacts/${encodeURIComponent(id)}/download`, {}, (response) => response.blob());
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url; link.download = name; link.hidden = true;
  document.body.appendChild(link); link.click(); link.remove();
  window.setTimeout(() => URL.revokeObjectURL(url), 1000);
}
export type Resource = { id: string; kind: string; name: string; slug: string; draft: Record<string, unknown>; revision: number; latest_version: number; active_version: number | null; archived: boolean; updated_at: number };
export type Run = { id: string; resource_id: string; resource_version: number; status: string; output: Record<string, unknown>; error?: string; event_sequence: number; created_at: number; finished_at?: number };
