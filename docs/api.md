# API guide

Eivon exposes a versioned JSON API under `/api/v1`. FastAPI publishes the generated OpenAPI document at `/openapi.json` and interactive docs at `/docs`.

## Request identity

Browser sessions use an HttpOnly `eivon_session` cookie. Setup and login return a CSRF token; send it as `x-csrf-token` for cookie based mutations. Automation can use a workspace-scoped `Authorization: Bearer eiv_...` API key. API keys are shown only once at creation. Send `x-eivon-workspace` to explicitly select a browser session workspace; bearer keys cannot select a different workspace. The console sends this header for all scoped requests, including downloads. See [workspace administration](administration.md) for membership, credentials, key revocation, audit and session recovery.

## Resource lifecycle

`POST /resources` creates a draft. `POST /resources/{id}/validate` validates its Pydantic contract and dependency graph. `POST /resources/{id}/publish` creates an immutable version; `POST /resources/{id}/activate` selects the active version. Agent and Workflow Runs reference the selected version and keep a complete dependency snapshot.

## Execution lifecycle

Create a Run with `POST /runs`, read ordered events with `GET /runs/{id}/events`, or stream them from `/runs/{id}/events/stream`. `POST /runs/{id}/cancel` requests cancellation. A Run that needs human input or a write approval enters `waiting_input` or `waiting_approval`; resume it with `POST /runs/{id}/resume` and the event sequence returned by the Run resource.

## Domain data

Knowledge collections and documents use `/knowledge/collections` and `/knowledge/documents`; lexical retrieval is available at `/knowledge/search`. Domain packages should put their business context, tools and authorization in Bundles or trusted extensions while keeping core resource contracts stable.

## Evaluations

Create a JSON evaluation set with `POST /evaluations`. Each case has an `input`, an optional `context`, an `expected` string and a `match` mode (`contains`, `exact` or `nonempty`). `POST /evaluations/{id}/run` creates one immutable Run per case and returns a durable evaluation Job. Poll `/evaluation-jobs/{id}` for that exact batch’s case results and aggregate score. `/evaluations/{id}/jobs` lists paginated history; `/evaluation-comparison` compares two compatible completed batches. Human reviews and reviewed Prompt/Skill candidates are documented in the [evaluation guide](evaluations.md).

## MCP tools

A Tool resource may use `adapter: mcp` with `config.url` and an optional `config.tool`. Eivon sends a Streamable HTTP JSON-RPC `tools/call` request through the same outbound host allowlist, credential, timeout, result-size and approval checks as HTTP tools. Server discovery and process-hosted transports belong in deployment extensions.

## Workflow execution

Workflow Runs accept a separate `input` object validated against the published workflow schema. The [workflow guide](workflows.md) documents typed data bindings, conditions, input/approval resume and per-step model selection. Both Workflow Studio and Run history provide an interactive Run inspector.

## Conversations and generated files

Create a conversation with `POST /sessions` (`agent_id`, `title`, `context`), then send `session_id` in each `POST /runs` request. `GET /sessions/{id}` returns the persisted turns. Only one active or waiting Run is allowed per session. `GET /runs/{id}/artifacts` lists its authorized generated files; use `/artifacts/{id}/download` for authenticated downloads, including Unicode filenames. See the [conversation guide](conversations.md).

## Resource inspection and restoration

`GET /resources` supports `kind`, `search`, `offset`, `limit` and `archived` (default `false`). `archived=true` lists only archived resources in the authenticated workspace. `POST /resources/{id}/validate` accepts an optional `{"revision": N}` body to reject stale validation. Activation and archive/restore require the current revision. The [resource guide](resources.md) distinguishes activation rollback from copying a release into a new draft.
