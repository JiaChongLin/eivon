# API guide

Eivon exposes a versioned JSON API under `/api/v1`. FastAPI publishes the generated OpenAPI document at `/openapi.json` and interactive docs at `/docs`.

## Request identity

Browser sessions use an HttpOnly `eivon_session` cookie. Setup and login return a CSRF token; send it as `x-csrf-token` for cookie based mutations. Automation can use a workspace-scoped `Authorization: Bearer eiv_...` API key. API keys are shown only once at creation.

## Resource lifecycle

`POST /resources` creates a draft. `POST /resources/{id}/validate` validates its Pydantic contract and dependency graph. `POST /resources/{id}/publish` creates an immutable version; `POST /resources/{id}/activate` selects the active version. Agent and Workflow Runs reference the selected version and keep a complete dependency snapshot.

## Execution lifecycle

Create a Run with `POST /runs`, read ordered events with `GET /runs/{id}/events`, or stream them from `/runs/{id}/events/stream`. `POST /runs/{id}/cancel` requests cancellation. A Run that needs human input or a write approval enters `waiting_input` or `waiting_approval`; resume it with `POST /runs/{id}/resume` and the event sequence returned by the Run resource.

## Domain data

Knowledge collections and documents use `/knowledge/collections` and `/knowledge/documents`; lexical retrieval is available at `/knowledge/search`. Domain packages should put their business context, tools and authorization in Bundles or trusted extensions while keeping core resource contracts stable.
