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
- [ ] Evaluations, version comparisons and reviewed improvement suggestions
- [x] Complete console: setup, dashboard, agents, resources, playground, chat
- [ ] Complete console: runs, knowledge, evaluations, approvals, members, settings (runs, knowledge, approvals and members are now present; evaluations and richer administration remain)
- [x] Workflow baseline execution with documented supported semantics (visual editing remains)
- [x] HTTP and trusted Python extension integration; MCP adapter remains
- [x] Generic starter examples and two distinct synthetic domain bundles
- [x] Docker/Compose, initial schema bootstrap and deployment instructions
- [x] README, architecture, API, extension, operations and contribution documentation
- [x] License and publication inventory; clean export tooling remains
- [x] Backend contracts/integration tests and frontend build
- [ ] Multi-worker cancellation/recovery, permission and failure-mode verification
- [ ] Clean-machine startup and release artifact verification

## Implementation log

2026-09-20: Created a standalone distribution directory and package skeleton.
Current FarmLynk application code and pre-existing untracked files are untouched.
2026-09-20: Added durable Run worker, workflow baseline execution, knowledge APIs, management console, Docker/Compose and 23 automated tests. Browser E2E, formal migrations, MCP, isolated extension runner and evaluation UI remain open release work.
2026-09-20: Added Knowledge and Members console pages plus an approval card in Playground so waiting Runs can be resumed from the UI.

2026-09-20: Created independent Eivon project in ~/work/eivon. Original scaffold retained.
