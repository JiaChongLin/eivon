# Eivon architecture

Eivon is a modular monolith with a control plane and a durable execution plane. The public contracts live under `src/eivon/core`; they do not import FastAPI, SQLAlchemy, a model vendor, or a business domain.

```text
console / SDK
      │
      ▼
FastAPI ── Security ── Resources (draft → publish → immutable snapshot)
      │                             │
      ├── Sessions / Runs / Events ──┘
      │          │
      │          └── worker lease → AgentEngine → Model + ToolRuntime
      │                                      ├── trusted extension SDK
      │                                      ├── allowlisted HTTP adapter
      │                                      ├── knowledge retrieval
      │                                      └── private artifacts
      └── audit / health / management APIs
```

## Resource and release boundary

A resource draft is mutable and has an optimistic `revision`. Publishing validates its Pydantic contract, resolves every dependency to one exact version, checks credentials and workspace ownership, and stores an immutable snapshot digest. Runs only read that snapshot. Activating or publishing a newer version therefore cannot change a running execution.

The `AgentSpec` composes a model, prompts, skills, tools, Bundles, workflows and knowledge collections. A Bundle is a resource combination, not a hard-coded industry enum. Extension modules are installed by the deployment operator and register async handlers by name.

## Execution boundary

The API creates a queued Run. The worker claims it with a database lease and writes ordered `RunEvent` rows. A Run can be `running`, `waiting_input`, `waiting_approval`, `cancelling`, `completed`, `failed` or `cancelled`. The engine saves its serializable state before tool execution and on every iteration. A stale lease is terminalized with an explicit warning because an external side effect may already have completed.

Tool execution validates the published input schema, checks the current permission and approval policy, enforces a timeout and result byte budget, and only then calls the adapter. Outbound network calls must match a deployment allowlist. Python extensions are trusted code and require process/container isolation when used with untrusted packages.

## Identity boundary

Session cookies are HttpOnly and SameSite strict. Mutating cookie requests require the server-issued CSRF token. API keys are hashed at rest, workspace bound, permission subsets of the issuing principal, and returned only at creation. Credentials are encrypted with a server-owned Fernet key and never included in resource or list responses. Every resource, session, Run and artifact is checked against the authenticated workspace at execution time.

## Domain extension boundary

The core uses `business_context: dict` only as a validated extension-owned payload. A domain package owns its entity schema, data adapter, tools, skills, workflows and row-level authorization. It must not modify core routing or add keyword-based intent trees. The same framework can host unrelated Bundles in separate workspaces.

## Current supported baseline

The baseline console supports setup, sign-in, resource drafts, JSON editing/publishing and a structured Workflow Studio, Agent composition from published model/Prompt resources, Playground execution, Run history, evaluations, knowledge collection/document ingestion, encrypted credentials and workspace administration. The runtime supports model streaming, offline demo model, HTTP/Python/MCP tools, approval waits, input waits, resumable workflow steps, cancellation, durable evaluation batches and ordered events.

A stable open-source release still requires broader browser E2E, isolated extension runners, version-comparison workflows and production operations hardening. Those are tracked in `docs/DELIVERY.md`; this document does not silently claim those items are complete.
