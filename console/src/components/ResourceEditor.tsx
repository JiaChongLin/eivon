import { useEffect, useState } from "react";
import { api } from "../api";
import type { Resource } from "../api";
import { diffSpec, parseSpec } from "./resourceSpec";

type Version = { version: number; spec: Record<string, unknown>; digest: string; created_at: number; snapshot?: { resources: Record<string, { name: string; kind: string; version: number }> } };
const format = (value: unknown) => value === undefined ? "(missing)" : JSON.stringify(value, null, 2);

export function ResourceEditor({ item, canWrite, onClose, onChanged }: { item: Resource; canWrite: boolean; onClose: () => void; onChanged: (close?: boolean) => void }) {
  const [current, setCurrent] = useState(item);
  const [name, setName] = useState(item.name);
  const [draft, setDraft] = useState(format(item.draft));
  const [versions, setVersions] = useState<Version[]>([]);
  const [version, setVersion] = useState(item.active_version || 0);
  const [compare, setCompare] = useState("draft");
  const [release, setRelease] = useState<Version | null>(null);
  const [error, setError] = useState("");
  const [message, setMessage] = useState("");
  const [busy, setBusy] = useState(false);
  const dirty = name !== current.name || draft !== format(current.draft);
  useEffect(() => {
    const controller = new AbortController();
    api<{ items: Version[] }>(`/resources/${item.id}/versions`, { signal: controller.signal }).then((result) => {
      setVersions(result.items); setVersion((previous) => previous || result.items[0]?.version || 0);
    }).catch((e) => { if (!controller.signal.aborted) setError(e.message); });
    return () => controller.abort();
  }, [item.id]);
  useEffect(() => {
    setRelease(null);
    if (!version) return;
    const controller = new AbortController();
    api<Version>(`/resources/${item.id}/versions/${version}`, { signal: controller.signal }).then(setRelease).catch((e) => { if (!controller.signal.aborted) setError(e.message); });
    return () => controller.abort();
  }, [item.id, version]);

  function adopt(value: Resource) { setCurrent(value); setName(value.name); setDraft(format(value.draft)); }
  async function perform(action: () => Promise<void>) {
    setBusy(true); setError(""); setMessage("");
    try { await action(); } catch (e) { setError((e as Error).message); } finally { setBusy(false); }
  }
  async function saveDraft(): Promise<Resource> {
    if (!name.trim()) throw new Error("Enter a resource name");
    const saved = await api<Resource>(`/resources/${item.id}`, { method: "PUT", body: JSON.stringify({ revision: current.revision, name, spec: parseSpec(draft) }) });
    adopt(saved); return saved;
  }
  async function publish() {
    const saved = dirty ? await saveDraft() : current;
    await api(`/resources/${item.id}/publish`, { method: "POST", body: JSON.stringify({ revision: saved.revision }) });
    onChanged();
  }
  async function activate() {
    const activated = await api<Resource>(`/resources/${item.id}/activate`, { method: "POST", body: JSON.stringify({ revision: current.revision, version }) });
    // Keep local edits while advancing the optimistic revision after activation.
    setCurrent(activated); setMessage(`Active release changed to v${version}. Existing Runs retain their snapshots.`); onChanged(false);
  }
  async function archive() {
    await api(`/resources/${item.id}/archive`, { method: "POST", body: JSON.stringify({ revision: current.revision, archived: !current.archived }) });
    onChanged();
  }
  let comparison: Record<string, unknown> | undefined; let comparisonError = "";
  try { comparison = compare === "draft" ? parseSpec(draft) : versions.find((entry) => String(entry.version) === compare)?.spec; } catch (e) { comparisonError = (e as Error).message; }
  const changes = release && comparison ? diffSpec(release.spec, comparison) : [];
  return <div className="modal-backdrop"><div className="modal resource-editor-modal" role="dialog" aria-label="Edit resource" aria-modal="true">
    <div className="modal-header"><div><span className="eyebrow">RESOURCE / {item.kind}</span><h2>{current.name}</h2></div><button disabled={busy} className="icon-button" aria-label="Close" onClick={onClose}>×</button></div>
    {error && <div role="alert" className="notice error">{error}<button disabled={busy} className="text-button" onClick={() => void perform(async () => { const [latest, history] = await Promise.all([api<Resource>(`/resources/${item.id}`), api<{ items: Version[] }>(`/resources/${item.id}/versions`)]); adopt(latest); setVersions(history.items); setVersion(latest.active_version || history.items[0]?.version || 0); onChanged(false); setMessage("Latest saved draft loaded"); })}>Discard edits and reload</button></div>}
    {message && <div role="status" className="notice">{message}</div>}
    <div className="detail-list"><span>Draft revision <b>{current.revision}</b></span><span>Active release <b data-testid="active-version">{current.active_version ? `v${current.active_version}` : "Not published"}</b></span><span>State <b>{current.archived ? "Archived" : "Active"}</b></span></div>
    <div className="resource-editor-columns"><section aria-label="Resource draft"><h3>Draft {dirty && <small className="muted">· Unsaved changes</small>}</h3>
      <label>Name<input required maxLength={160} readOnly={!canWrite || current.archived} disabled={busy} value={name} onChange={(e) => setName(e.target.value)} /></label>
      <label>Draft JSON<textarea className="code-editor" readOnly={!canWrite || current.archived} disabled={busy} value={draft} onChange={(e) => setDraft(e.target.value)} /></label>
      {canWrite && !current.archived && <><p className="muted">Publishing saves these edits and creates a new immutable release.</p><div className="modal-actions"><button className="button" disabled={busy} onClick={() => void perform(async () => { await saveDraft(); onChanged(); })}>Save draft</button><button className="button" disabled={busy} onClick={() => void perform(publish)}>Publish release</button></div><button className="text-button validate-button" disabled={busy || dirty} onClick={() => void perform(async () => { const result = await api<{ dependencies: number }>(`/resources/${item.id}/validate`, { method: "POST", body: JSON.stringify({ revision: current.revision }) }); setMessage(`Saved draft is valid · ${result.dependencies} pinned dependencies`); })}>Validate saved draft</button></>}
    </section><section aria-label="Release history"><h3>Release history</h3>{!versions.length ? <p className="muted">No published releases yet.</p> : <>
      <label>Release version<select value={version} disabled={busy} onChange={(e) => setVersion(Number(e.target.value))}>{versions.map((entry) => <option key={entry.version} value={entry.version}>v{entry.version}{entry.version === current.active_version ? " · active" : ""}</option>)}</select></label>
      {release && <><p className="muted">Published {new Date(release.created_at * 1000).toLocaleString()}</p><details><summary>Immutable specification and digest</summary><pre>{format(release.spec)}</pre><code className="digest">{release.digest}</code></details><details><summary>Pinned dependencies</summary><ul className="muted">{Object.entries(release.snapshot?.resources || {}).map(([key, child]) => <li key={key}>{child.name} · {child.kind} · v{child.version}</li>)}</ul></details>
        {canWrite && !current.archived && <div className="workflow-actions"><button className="button" disabled={busy || version === current.active_version} onClick={() => void perform(activate)}>Activate v{version}</button><button className="text-button" disabled={busy} onClick={() => { setDraft(format(release.spec)); setMessage(`Copied v${version} into the editor. Save or publish to persist it.`); }}>Use v{version} as draft</button></div>}
        <p className="muted">Activating a release changes future Runs. It preserves both the saved draft and existing Run snapshots.</p>
        <label>Compare with<select value={compare} disabled={busy} onChange={(e) => setCompare(e.target.value)}><option value="draft">Editor draft</option>{versions.map((entry) => <option key={entry.version} value={entry.version}>v{entry.version}</option>)}</select></label>
        {comparisonError ? <p className="notice error">{comparisonError}</p> : <section className="spec-comparison" aria-label="Specification differences">{!changes.length ? <p className="muted">No specification changes.</p> : <><div className="comparison-head"><span>v{version}</span><span>{compare === "draft" ? "Editor draft" : `v${compare}`}</span></div>{changes.map((change) => <article key={change.path}><code>{change.path}</code><div><pre>{format(change.before)}</pre><pre>{format(change.after)}</pre></div></article>)}</>}</section>}
      </>}
    </>}</section></div>
    <div className="modal-actions">{canWrite && <button className="text-button" disabled={busy || dirty} onClick={() => void perform(archive)}>{current.archived ? "Restore resource" : "Archive resource"}</button>}<span className="workflow-spacer" /><button className="text-button" disabled={busy} onClick={onClose}>Close</button></div>
  </div></div>;
}
