import { useEffect, useState } from "react";
import { api } from "../api";
import type { Run } from "../api";

type RunDetail = Run & { checkpoint?: { waiting?: Record<string, unknown> }; snapshot?: { root: { name: string }; resources: Record<string, { name: string; version: number }> } };
type Event = { sequence: number; type: string; data: Record<string, unknown> };
const stopped = new Set(["completed", "failed", "cancelled", "waiting_input", "waiting_approval"]);

export function RunInspector({ runId }: { runId: string }) {
  const [run, setRun] = useState<RunDetail | null>(null);
  const [events, setEvents] = useState<Event[]>([]);
  const [response, setResponse] = useState("{}");
  const [error, setError] = useState("");
  const [revision, setRevision] = useState(0);
  const [busy, setBusy] = useState(false);
  useEffect(() => {
    const controller = new AbortController();
    let timer: number | undefined;
    let sequence = 0;
    setRun(null); setEvents([]); setError("");
    async function poll() {
      try {
        const [current, next] = await Promise.all([
          api<RunDetail>(`/runs/${runId}`, { signal: controller.signal }),
          api<{ items: Event[] }>(`/runs/${runId}/events?after=${sequence}&limit=500`, { signal: controller.signal }),
        ]);
        if (controller.signal.aborted) return;
        setRun(current);
        if (next.items.length) {
          sequence = next.items[next.items.length - 1].sequence;
          setEvents((previous) => [...previous, ...next.items]);
        }
        if (!stopped.has(current.status) || sequence < current.event_sequence) timer = window.setTimeout(poll, 400);
      } catch (e) { if (!controller.signal.aborted) setError((e as Error).message); }
    }
    void poll();
    return () => { controller.abort(); window.clearTimeout(timer); };
  }, [runId, revision]);

  async function act(action: "resume" | "cancel", approved?: boolean) {
    if (!run) return;
    setBusy(true); setError("");
    try {
      const answer = action === "cancel" ? {} : approved === undefined ? JSON.parse(response) : { approved };
      if (action === "resume" && (answer === null || Array.isArray(answer) || typeof answer !== "object")) throw new Error("Response must be a JSON object");
      await api(`/runs/${runId}/${action}`, { method: "POST", body: action === "resume" ? JSON.stringify({ expected_sequence: run.event_sequence, response: answer }) : undefined });
      setRevision((value) => value + 1);
    } catch (e) { setError((e as Error).message); } finally { setBusy(false); }
  }
  const waiting = run?.checkpoint?.waiting;
  return <section className="run-inspector settings-card" aria-label="Run details">
    <div className="toolbar"><div><h3>{run?.snapshot?.root.name || "Run"}</h3><small className="mono">{runId}</small></div><span className="badge" role="status">{run?.status || "loading"}</span></div>
    {error && <div className="notice error" role="alert">{error}<button className="text-button" onClick={() => setRevision((value) => value + 1)}>Refresh run</button></div>}
    {run?.error && <div className="notice error">{run.error}</div>}
    {run?.status === "waiting_input" && <form onSubmit={(e) => { e.preventDefault(); void act("resume"); }}><h4>{String(waiting?.question || "Provide input")}</h4><details><summary>Required input schema</summary><pre>{JSON.stringify(waiting?.input_schema, null, 2)}</pre></details><label>Response JSON<textarea value={response} onChange={(e) => setResponse(e.target.value)} /></label><button className="button" disabled={busy}>Resume workflow</button></form>}
    {run?.status === "waiting_approval" && <div className="approval-card"><h4>Approve {String(waiting?.tool || "tool execution")}</h4><pre>{JSON.stringify(waiting?.arguments, null, 2)}</pre><div><button className="button" disabled={busy} onClick={() => void act("resume", true)}>Approve</button><button className="text-button" disabled={busy} onClick={() => void act("resume", false)}>Decline</button></div></div>}
    {run && !["completed", "failed", "cancelled"].includes(run.status) && <button className="text-button" disabled={busy} onClick={() => void act("cancel")}>Cancel run</button>}
    {run?.output && <div><h4>Output</h4><pre data-testid="run-output">{typeof run.output.text === "string" ? run.output.text : JSON.stringify(run.output, null, 2)}</pre></div>}
    <details><summary>Release dependencies · v{run?.resource_version}</summary><ul>{Object.entries(run?.snapshot?.resources || {}).map(([key, item]) => <li key={key}>{item.name} · v{item.version}</li>)}</ul></details>
    <details open><summary>Execution timeline · {events.length} events</summary><ol className="run-events">{events.map((event) => <li key={event.sequence}><strong>{event.type}</strong><pre>{JSON.stringify(event.data, null, 2)}</pre></li>)}</ol></details>
  </section>;
}
