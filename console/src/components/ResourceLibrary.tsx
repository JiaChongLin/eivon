import { useCallback, useEffect, useState } from "react";
import type { FormEvent } from "react";
import { api } from "../api";
import type { Resource } from "../api";
import { ResourceEditor } from "./ResourceEditor";
import { parseSpec } from "./resourceSpec";

const kinds = ["model", "prompt", "tool", "skill", "bundle", "workflow", "agent", "connection"];
const templates: Record<string, Record<string, unknown>> = {
  tool: { description: "Echo input for demonstration", adapter: "builtin", entrypoint: "echo", input_schema: { type: "object" }, effect: "read" },
  skill: { description: "A reusable method", body: "Describe the method here.", tool_refs: [], preload: false },
  bundle: { description: "A reusable capability bundle", tool_refs: [], skill_refs: [], prompt_refs: [], workflow_refs: [], knowledge_collection_ids: [], context_schema: { type: "object" } },
  workflow: { description: "A portable workflow", steps: [{ type: "input", id: "request", question: "What should be done?" }] },
  connection: { adapter: "http", base_url: "https://api.example.com", description: "A shared connection configuration" },
};
export function ResourceList({ kind, title, empty, canWrite }: { kind?: string; title: string; empty?: string; canWrite: boolean }) {
  const [items, setItems] = useState<Resource[]>([]);
  const [total, setTotal] = useState(0);
  const [offset, setOffset] = useState(0);
  const [searchText, setSearchText] = useState("");
  const [search, setSearch] = useState("");
  const [filterKind, setFilterKind] = useState("");
  const [archived, setArchived] = useState(false);
  const [refresh, setRefresh] = useState(0);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [show, setShow] = useState(false);
  const [selected, setSelected] = useState<Resource | null>(null);
  useEffect(() => {
    const controller = new AbortController();
    const query = new URLSearchParams({ offset: String(offset), limit: "24", search, archived: String(archived) });
    if (kind || filterKind) query.set("kind", kind || filterKind);
    setLoading(true); setError("");
    api<{ items: Resource[]; total: number }>(`/resources?${query}`, { signal: controller.signal })
      .then((data) => { setItems(data.items); setTotal(data.total); })
      .catch((e) => { if (!controller.signal.aborted) setError(e.message); })
      .finally(() => { if (!controller.signal.aborted) setLoading(false); });
    return () => controller.abort();
  }, [kind, filterKind, offset, search, archived, refresh]);
  const changed = useCallback((close = true) => { if (close) setSelected(null); setRefresh((value) => value + 1); }, []);
  return <section>
    <div className="toolbar"><div><span className="eyebrow">VERSIONED ASSETS</span><h2 className="section-title">{title}</h2></div>{canWrite && <button className="button" onClick={() => setShow(true)}>+ New resource</button>}</div>
    <form className="resource-filters" onSubmit={(event) => { event.preventDefault(); setSearch(searchText); setOffset(0); }}>
      <label>Search resources<input value={searchText} maxLength={200} onChange={(e) => setSearchText(e.target.value)} placeholder="Search names…" /></label>
      {!kind && <label>Resource type<select value={filterKind} onChange={(e) => { setFilterKind(e.target.value); setOffset(0); }}><option value="">All types</option>{kinds.map((value) => <option key={value} value={value}>{value}</option>)}</select></label>}
      <label>Resource state<select value={String(archived)} onChange={(e) => { setArchived(e.target.value === "true"); setOffset(0); }}><option value="false">Active</option><option value="true">Archived</option></select></label>
      <button className="button">Search</button><button type="button" className="text-button" onClick={() => setRefresh((value) => value + 1)}>Refresh</button>
    </form>
    {error && <div role="alert" className="notice error">{error}</div>}
    <div aria-busy={loading}>{!loading && !items.length ? <div className="empty"><h3>{search || archived ? "No matching resources" : empty || "No resources yet"}</h3><p>Create, publish and compose resources for your workspace.</p></div> : <div className="resource-grid">{items.map((item) => <button className="resource-card" key={item.id} onClick={() => setSelected(item)}><div className="card-top"><span className="badge">{item.kind}</span><span className={item.active_version ? "published" : "draft"}>{item.archived ? "ARCHIVED" : item.active_version ? `v${item.active_version}` : "DRAFT"}</span></div><h3>{item.name}</h3><p>{item.slug}</p><small>Updated {new Date(item.updated_at * 1000).toLocaleString()}</small></button>)}</div>}</div>
    <div className="workflow-actions"><button className="text-button" disabled={!offset || loading} onClick={() => setOffset((value) => Math.max(0, value - 24))}>Previous</button><span className="muted">{total ? offset + 1 : 0}–{Math.min(offset + items.length, total)} of {total}</span><button className="text-button" disabled={offset + items.length >= total || loading} onClick={() => setOffset((value) => value + 24)}>Next</button></div>
    {show && <ResourceDialog kind={kind} onClose={() => setShow(false)} onCreated={() => { setShow(false); setArchived(false); setOffset(0); setSearch(""); setSearchText(""); setFilterKind(""); setRefresh((value) => value + 1); }} />}
    {selected && <ResourceEditor key={selected.id} item={selected} canWrite={canWrite} onClose={() => setSelected(null)} onChanged={changed} />}
  </section>;
}

async function published(kind: string): Promise<Resource[]> {
  const items: Resource[] = [];
  for (let offset = 0; ; offset += 200) {
    const page = await api<{ items: Resource[]; total: number }>(`/resources?kind=${kind}&offset=${offset}&limit=200`);
    items.push(...page.items.filter((item) => item.active_version));
    if (!page.items.length || offset + page.items.length >= page.total) return items;
  }
}
function ResourceDialog({ kind, onClose, onCreated }: { kind?: string; onClose: () => void; onCreated: () => void }) {
  const [resourceKind, setResourceKind] = useState(kind || "prompt");
  const [name, setName] = useState("");
  const [slug, setSlug] = useState("");
  const [template, setTemplate] = useState("You are a helpful assistant. Use available tools when needed.");
  const [provider, setProvider] = useState("demo");
  const [modelName, setModelName] = useState("offline-demo");
  const [baseUrl, setBaseUrl] = useState("https://api.openai.com/v1");
  const [credentialId, setCredentialId] = useState("");
  const [credentials, setCredentials] = useState<{ id: string; name: string }[]>([]);
  const [specs, setSpecs] = useState<Record<string, string>>({});
  const [modelId, setModelId] = useState("");
  const [promptId, setPromptId] = useState("");
  const [models, setModels] = useState<Resource[]>([]);
  const [prompts, setPrompts] = useState<Resource[]>([]);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  useEffect(() => {
    let mounted = true;
    if (resourceKind === "agent") Promise.all([published("model"), published("prompt")]).then(([models, prompts]) => { if (mounted) { setModels(models); setPrompts(prompts); } }).catch((e) => { if (mounted) setError(e.message); });
    if (resourceKind === "model") api<{ items: { id: string; name: string }[] }>("/credentials").then((result) => { if (mounted) setCredentials(result.items); }).catch((e) => { if (mounted) setError(e.message); });
    return () => { mounted = false; };
  }, [resourceKind]);
  async function submit(event: FormEvent) {
    event.preventDefault(); setError(""); setBusy(true);
    try {
      let spec: Record<string, unknown>;
      if (resourceKind === "prompt") spec = { template };
      else if (resourceKind === "model") spec = { provider, model: modelName, base_url: baseUrl, credential_id: credentialId || null };
      else if (resourceKind === "agent") {
        const model = models.find((item) => item.id === modelId);
        if (!model?.active_version) throw new Error("Choose a published model");
        spec = { model_ref: { id: model.id, version: model.active_version }, prompt_refs: promptId ? [{ id: promptId, version: prompts.find((item) => item.id === promptId)?.active_version }] : [] };
      } else spec = parseSpec(specs[resourceKind] ?? JSON.stringify(templates[resourceKind]));
      await api("/resources", { method: "POST", body: JSON.stringify({ kind: resourceKind, name, slug, spec }) });
      onCreated();
    } catch (e) { setError((e as Error).message); } finally { setBusy(false); }
  }
  return <div className="modal-backdrop"><form className="modal resource-modal" role="dialog" aria-label="Create resource" aria-modal="true" onSubmit={(event) => void submit(event)}>
    <div className="modal-header"><div><span className="eyebrow">NEW RESOURCE</span><h2>{resourceKind}</h2></div><button disabled={busy} type="button" className="icon-button" aria-label="Close" onClick={onClose}>×</button></div>
    {error && <div role="alert" className="notice error">{error}</div>}
    <fieldset disabled={busy}>{!kind && <label>Type<select value={resourceKind} onChange={(e) => { setResourceKind(e.target.value); setError(""); }}>{kinds.map((value) => <option key={value} value={value}>{value[0].toUpperCase() + value.slice(1)}</option>)}</select></label>}
      <label>Name<input required maxLength={160} value={name} onChange={(e) => setName(e.target.value)} /></label><label>Slug<input required pattern="[a-z][a-z0-9_.-]{1,99}" value={slug} onChange={(e) => setSlug(e.target.value)} /></label>
      {resourceKind === "prompt" && <label>Template<textarea value={template} onChange={(e) => setTemplate(e.target.value)} /></label>}
      {resourceKind === "model" && <><label>Provider<select value={provider} onChange={(e) => setProvider(e.target.value)}><option value="demo">Offline demo</option><option value="openai_compatible">OpenAI-compatible</option></select></label><label>Model<input required value={modelName} onChange={(e) => setModelName(e.target.value)} /></label>{provider === "openai_compatible" && <><label>Base URL<input required type="url" value={baseUrl} onChange={(e) => setBaseUrl(e.target.value)} /></label><label>Credential<select value={credentialId} onChange={(e) => setCredentialId(e.target.value)}><option value="">No credential</option>{credentials.map((item) => <option key={item.id} value={item.id}>{item.name}</option>)}</select></label><p className="muted">Create encrypted credentials in Settings. The deployment must allow the provider host.</p></>}</>}
      {templates[resourceKind] && <label>Specification JSON<textarea required className="code-editor" value={specs[resourceKind] ?? JSON.stringify(templates[resourceKind], null, 2)} onChange={(e) => setSpecs((previous) => ({ ...previous, [resourceKind]: e.target.value }))} /></label>}
      {resourceKind === "agent" && <><label>Published model<select required value={modelId} onChange={(e) => setModelId(e.target.value)}><option value="">Choose a model</option>{models.map((item) => <option key={item.id} value={item.id}>{item.name} · v{item.active_version}</option>)}</select></label><label>Published system Prompt<select value={promptId} onChange={(e) => setPromptId(e.target.value)}><option value="">No prompt</option>{prompts.map((item) => <option key={item.id} value={item.id}>{item.name} · v{item.active_version}</option>)}</select></label><p className="muted">Use the draft editor to add tools, skills, bundles, knowledge and execution policy before publishing.</p></>}
      <button className="button" type="submit">Create draft</button>
    </fieldset>
  </form></div>;
}
