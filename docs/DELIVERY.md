# Delivery and verification

Source plan: `design/open_source_agent_framework.md`. This checklist preserves the full open-source product scope.

Status: runnable foundation release. The repository is still pre-1.0; the unchecked items below are deliberate release work.

- [x] Independent package, CLI and documented installation
- [x] Authentication, workspaces, membership, roles, scoped API keys and audit
- [x] Encrypted credentials and configurable model providers
- [x] Typed tools, skills, prompts, bundles, workflows and extension SDK
- [x] Resource drafts, optimistic concurrency, immutable versions and agent releases
- [x] Agent loop with model streaming, tools, budgets, cancellation and checkpoints
- [x] Execution-time authorization, tool approvals and safe extension boundaries (trusted Python extensions remain deployment-scoped)
- [x] Durable runs, ordered events, sessions, artifacts and worker coordination
- [x] Knowledge ingestion, lexical retrieval and source metadata; semantic citations and connection management remain
- [x] Evaluation sets, batch Runs and deterministic result scoring; version comparison and reviewed improvement suggestions remain
- [x] Complete console: setup, dashboard, agents, resources, playground, chat
- [x] Complete console: runs, knowledge, evaluations, approvals, members, settings (richer administration and version comparison remain)
- [x] Workflow baseline execution with documented supported semantics (visual editing remains)
- [x] HTTP, trusted Python and Streamable HTTP MCP tool integration
- [x] Generic starter examples and two distinct synthetic domain bundles
- [x] Docker/Compose, versioned schema bootstrap and deployment instructions
- [x] README, architecture, API, extension, operations and contribution documentation
- [x] License, publication inventory and clean export tooling
- [x] Backend contracts/integration tests and frontend build
- [x] Multi-worker lease fencing, cancellation/recovery and permission/failure-mode coverage (high-load stress testing remains)
- [x] Clean-machine startup and release artifact verification

## Implementation log

2026-09-20: Created a standalone distribution directory and package skeleton.
Current FarmLynk application code and pre-existing untracked files are untouched.
2026-09-20: Added durable Run worker, workflow baseline execution, knowledge APIs, management console, Docker/Compose and 35 automated tests. Browser E2E, isolated extension runners, version comparisons and production operations hardening remain open release work.
2026-09-20: Added Knowledge and Members console pages plus an approval card in Playground so waiting Runs can be resumed from the UI.
2026-09-20: Added schema migration CLI, persisted evaluation sets/results, evaluation console, MCP Streamable HTTP calls, clean source export tooling and lease-fencing coverage.
2026-09-20: Verified a tracked-file export on a clean temporary directory: schema migration, worker startup, Python wheel build and console install/build all succeeded.

2026-09-20: Created independent Eivon project in ~/work/eivon. Original scaffold retained.
