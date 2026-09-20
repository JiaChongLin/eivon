import { useEffect, useState } from "react";
import type { FormEvent } from "react";
import { api, ApiRequestError, cancelPendingRequests, setCsrf, setWorkspace } from "./api";
import type { Identity } from "./api";
import { ResourceList } from "./components/ResourceLibrary";
import { Playground } from "./components/Playground";
import { RunHistory } from "./components/RunHistory";
import { WorkflowStudio } from "./components/WorkflowStudio";
import { Evaluations } from "./components/Evaluations";
import { Members, Settings } from "./components/Administration";

type Page = "overview" | "agents" | "resources" | "workflows" | "playground" | "runs" | "evaluations" | "knowledge" | "members" | "settings";

function Button({ children, ...props }: React.ButtonHTMLAttributes<HTMLButtonElement>) { return <button className="button" {...props}>{children}</button>; }
function Badge({ children }: { children: React.ReactNode }) { return <span className="badge">{children}</span>; }

function rememberWorkspace(identity: Identity) {
  try { sessionStorage.setItem(`eivon.workspace.${identity.user.id}`, identity.workspace_id); } catch { /* Storage is optional. */ }
}

export function App() {
  const [identity, setIdentity] = useState<Identity | null>(null);
  const [setupRequired, setSetupRequired] = useState<boolean | null>(null);
  const [page, setPage] = useState<Page>("overview");
  const [error, setError] = useState("");
  const [switching, setSwitching] = useState(false);
  function adopt(value: Identity) {
    setWorkspace(value.workspace_id); setCsrf(value.csrf_token || ""); rememberWorkspace(value); setIdentity(value); setError("");
  }
  useEffect(() => {
    let active = true;
    async function initialize() {
      try {
        const setup = await api<{ initialized: boolean }>("/setup");
        if (!setup.initialized) { if (active) setSetupRequired(true); return; }
        try {
          let me = await api<Identity>("/auth/me");
          let saved = ""; try { saved = sessionStorage.getItem(`eivon.workspace.${me.user.id}`) || ""; } catch { /* Optional storage. */ }
          if (saved && saved !== me.workspace_id && me.workspaces.some((item) => item.id === saved)) {
            try { me = await api<Identity>("/auth/me", { headers: { "x-eivon-workspace": saved } }); } catch (e) { if (!(e instanceof ApiRequestError) || e.status !== 403) throw e; }
          }
          if (active) adopt(me);
        } catch (e) {
          if (e instanceof ApiRequestError && e.status === 403) {
            const session = await api<{ csrf_token: string }>("/auth/session");
            if (active) { setCsrf(session.csrf_token); setError(e.message); }
          } else if (!(e instanceof ApiRequestError) || e.status !== 401) throw e;
        }
        if (active) setSetupRequired(false);
      } catch (e) { if (active) { setError((e as Error).message); setSetupRequired(false); } }
    }
    void initialize(); return () => { active = false; };
  }, []);
  async function logout() {
    try { await api("/auth/logout", { method: "POST" }); cancelPendingRequests(); setWorkspace(""); setCsrf(""); setIdentity(null); setError(""); setPage("overview"); }
    catch (e) { setError((e as Error).message); }
  }
  async function switchWorkspace(id: string) {
    if (switching) return;
    setSwitching(true); cancelPendingRequests();
    try { adopt(await api<Identity>("/auth/me", { headers: { "x-eivon-workspace": id } })); setPage("overview"); }
    catch (e) { setError((e as Error).message); }
    finally { setSwitching(false); }
  }
  async function refreshIdentity() {
    try { const value = await api<Identity>("/auth/me"); adopt(value); if (page === "members" && !value.permissions.includes("admin")) setPage("overview"); }
    catch (e) { setError((e as Error).message); }
  }
  if (error) return <main className="center"><div className="settings-card"><div role="alert" className="notice error">{error}</div>{identity && <button className="button" onClick={() => void switchWorkspace("")}>Reload available workspace</button>}<button className="text-button" onClick={() => void logout()}>Sign out</button></div></main>;
  if (setupRequired === null || switching) return <main className="center"><div className="loading">{switching ? "Switching workspace…" : "Loading Eivon…"}</div></main>;
  if (setupRequired) return <AuthCard mode="setup" onComplete={(value) => { adopt(value); setSetupRequired(false); }} />;
  if (!identity) return <AuthCard mode="login" onComplete={adopt} />;
  return <Shell key={`${identity.workspace_id}:${identity.role}`} identity={identity} page={page} setPage={setPage} onLogout={() => void logout()} onWorkspaceChange={(id) => void switchWorkspace(id)} onIdentityRefresh={() => void refreshIdentity()} />;
}

function AuthCard({ mode, onComplete }: { mode: "login" | "setup"; onComplete: (value: Identity) => void }) {
  const [form, setForm] = useState({ setup_token: "", email: "", password: "", name: "", workspace_name: "My workspace" });
  const [error, setError] = useState("");
  async function submit(event: FormEvent) { event.preventDefault(); setError(""); try { const result = await api<Identity>(mode === "setup" ? "/setup" : "/auth/login", { method: "POST", body: JSON.stringify(mode === "setup" ? form : { email: form.email, password: form.password }) }); onComplete(result); } catch (e) { setError((e as Error).message); } }
  return <main className="center"><form className="auth-card" onSubmit={submit}><div className="wordmark">EIVON <span>AGENT WORKBENCH</span></div><h1>{mode === "setup" ? "Create your workspace" : "Welcome back"}</h1><p className="muted">{mode === "setup" ? "Set up the first administrator for this self-hosted instance." : "Sign in to manage your agents."}</p>{error && <div className="notice error">{error}</div>}{mode === "setup" && <><label>Setup token<input required value={form.setup_token} onChange={(e) => setForm({ ...form, setup_token: e.target.value })} /></label><label>Your name<input required value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} /></label><label>Workspace name<input required value={form.workspace_name} onChange={(e) => setForm({ ...form, workspace_name: e.target.value })} /></label></>}<label>Email<input required type="email" value={form.email} onChange={(e) => setForm({ ...form, email: e.target.value })} /></label><label>Password<input required type="password" value={form.password} onChange={(e) => setForm({ ...form, password: e.target.value })} /></label><Button type="submit">{mode === "setup" ? "Initialize Eivon" : "Sign in"}</Button></form></main>;
}

function Shell({ identity, page, setPage, onLogout, onWorkspaceChange, onIdentityRefresh }: { identity: Identity; page: Page; setPage: (page: Page) => void; onLogout: () => void; onWorkspaceChange: (id: string) => void; onIdentityRefresh: () => void }) {
  const nav: [Page, string, string][] = [["overview", "Overview", "01"], ["agents", "Agents", "02"], ["resources", "Resources", "03"], ["workflows", "Workflows", "04"], ["playground", "Playground", "05"], ["runs", "Run history", "06"], ["evaluations", "Evaluations", "07"], ["knowledge", "Knowledge", "08"], ["members", "Members", "09"], ["settings", "Settings", "10"]];
  return <div className="app-shell"><aside><div className="wordmark">EIVON <span>WORKBENCH</span></div><label className="workspace-picker">Workspace<select aria-label="Current workspace" value={identity.workspace_id} onChange={(e) => onWorkspaceChange(e.target.value)}>{identity.workspaces.map((item) => <option key={item.id} value={item.id}>{item.name}</option>)}</select></label>{nav.filter(([key]) => key !== "members" || identity.permissions.includes("admin")).map(([key, name, number]) => <button key={key} className={`nav-item ${page === key ? "active" : ""}`} onClick={() => setPage(key)}><span>{number}</span>{name}</button>)}<div className="side-bottom"><div className="avatar">{identity.user.name.slice(0, 1).toUpperCase()}</div><div><strong>{identity.user.name}</strong><small>{identity.user.email}</small></div><button className="logout" aria-label="Sign out" onClick={onLogout}>↗</button></div></aside><main className="content"><header><div><span className="eyebrow">CONTROL PLANE / {page.toUpperCase()}</span><h1>{nav.find(([key]) => key === page)?.[1]}</h1></div><div className="header-actions"><Badge>{identity.role}</Badge><span className="connection"><i /> Local instance</span></div></header>{page === "overview" && <Overview setPage={setPage} />}{page === "agents" && <ResourceList canWrite={identity.permissions.includes("write")} kind="agent" title="Agents" empty="Create an Agent release from model and prompt resources." />}{page === "resources" && <ResourceList canWrite={identity.permissions.includes("write")} title="Resource library" />}{page === "workflows" && <WorkflowStudio />}{page === "playground" && <Playground />}{page === "runs" && <RunHistory />}{page === "evaluations" && <Evaluations identity={identity} />}{page === "knowledge" && <Knowledge />}{page === "members" && <Members identity={identity} />}{page === "settings" && <Settings identity={identity} onWorkspaceChange={onWorkspaceChange} onIdentityRefresh={onIdentityRefresh} />}</main></div>;
}

function Overview({ setPage }: { setPage: (page: Page) => void }) { const [stats, setStats] = useState({ resources: 0, runs: 0 }); useEffect(() => { api<typeof stats>("/stats").then(setStats).catch(() => undefined); }, []); return <><section className="hero"><div><span className="eyebrow">A SYSTEM FOR BUILDING SYSTEMS</span><h2>Turn intent into<br /><em>capability.</em></h2><p>Configure models, tools, skills and workflows into agents that can reason, act and be observed.</p><Button onClick={() => setPage("playground")}>Open Playground <span>→</span></Button></div><div className="orb"><div className="orb-core" /><div className="orb-ring r1" /><div className="orb-ring r2" /></div></section><div className="metric-grid"><div className="metric"><span>ACTIVE RESOURCES</span><strong>{stats.resources}</strong><small>in this workspace</small></div><div className="metric"><span>EXECUTION RUNS</span><strong>{stats.runs}</strong><small>all time</small></div><div className="metric"><span>RUNTIME</span><strong>LOCAL</strong><small>self-hosted control plane</small></div><div className="metric"><span>VERSION</span><strong>0.1</strong><small>foundation release</small></div></div><section className="section-heading"><div><span className="eyebrow">GET STARTED</span><h3>Build your first agent</h3></div></section><div className="steps"><button onClick={() => setPage("resources")}><b>01</b><strong>Connect a model</strong><span>Choose a provider and test the connection →</span></button><button onClick={() => setPage("resources")}><b>02</b><strong>Add a capability</strong><span>Define a tool, skill or knowledge source →</span></button><button onClick={() => setPage("agents")}><b>03</b><strong>Publish an agent</strong><span>Compose resources and freeze a release →</span></button></div></>; }

type Collection = { id: string; name: string; description: string; created_at: number };
function Knowledge() { const [collections, setCollections] = useState<Collection[]>([]); const [selected, setSelected] = useState(""); const [name, setName] = useState(""); const [description, setDescription] = useState(""); const [title, setTitle] = useState(""); const [content, setContent] = useState(""); const [source, setSource] = useState(""); const [query, setQuery] = useState(""); const [hits, setHits] = useState<Record<string, unknown>[]>([]); const [error, setError] = useState(""); async function load() { try { const value = await api<{ items: Collection[] }>("/knowledge/collections"); setCollections(value.items); if (!selected && value.items[0]) setSelected(value.items[0].id); } catch (e) { setError((e as Error).message); } } useEffect(() => { load(); }, []); async function createCollection(event: FormEvent) { event.preventDefault(); try { await api("/knowledge/collections", { method: "POST", body: JSON.stringify({ name, description }) }); setName(""); setDescription(""); await load(); } catch (e) { setError((e as Error).message); } } async function addDocument(event: FormEvent) { event.preventDefault(); if (!selected) return; try { await api("/knowledge/documents", { method: "POST", body: JSON.stringify({ collection_id: selected, title, content, source_uri: source }) }); setTitle(""); setContent(""); setSource(""); setError(""); } catch (e) { setError((e as Error).message); } } async function search(event: FormEvent) { event.preventDefault(); if (!selected) return; try { const value = await api<{ items: Record<string, unknown>[] }>("/knowledge/search", { method: "POST", body: JSON.stringify({ collection_ids: [selected], query, limit: 8 }) }); setHits(value.items); } catch (e) { setError((e as Error).message); } } return <section><div className="toolbar"><div><span className="eyebrow">GROUNDED CONTEXT</span><h2 className="section-title">Knowledge</h2></div><Badge>{collections.length} collections</Badge></div>{error && <div className="notice error">{error}</div>}<div className="knowledge-grid"><form className="settings-card" onSubmit={createCollection}><h3>Create collection</h3><p className="muted">Keep domain documents isolated by workspace and release.</p><label>Name<input required value={name} onChange={(e) => setName(e.target.value)} placeholder="Product handbook" /></label><label>Description<input value={description} onChange={(e) => setDescription(e.target.value)} /></label><Button type="submit">Create collection</Button></form><form className="settings-card" onSubmit={addDocument}><h3>Index document</h3><label>Collection<select required value={selected} onChange={(e) => setSelected(e.target.value)}><option value="">Choose collection</option>{collections.map((item) => <option key={item.id} value={item.id}>{item.name}</option>)}</select></label><label>Title<input required value={title} onChange={(e) => setTitle(e.target.value)} placeholder="Getting started" /></label><label>Source URI<input value={source} onChange={(e) => setSource(e.target.value)} placeholder="https://…" /></label><label>Content<textarea required value={content} onChange={(e) => setContent(e.target.value)} placeholder="Paste text to index…" /></label><Button type="submit">Index document</Button></form></div><div className="settings-card knowledge-search"><h3>Search indexed context</h3><form className="composer" onSubmit={search}><div><input required value={query} onChange={(e) => setQuery(e.target.value)} placeholder="Search this collection…" /><Button type="submit">Search</Button></div></form>{hits.length === 0 ? <p className="muted">Search results will show source chunks and scores here.</p> : <div className="search-results">{hits.map((hit, index) => <article key={`${String(hit.chunk_id)}-${index}`}><div><Badge>{String(hit.score)} score</Badge><strong>{String(hit.title)}</strong></div><p>{String(hit.content)}</p>{typeof hit.source_uri === "string" && <small>{hit.source_uri}</small>}</article>)}</div>}</div></section>; }
