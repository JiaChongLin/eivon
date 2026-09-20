# Delivery and verification

Source plan: `design/open_source_agent_framework.md`. This checklist preserves the full open-source product scope.

Status: implementation in progress. No release is claimed yet.

- [x] Independent package, CLI and documented installation
- [x] Authentication, workspaces, membership, roles, scoped API keys and audit
- [x] Encrypted credentials and configurable model providers
- [x] Typed tools, skills, prompts, bundles, workflows and extension SDK
- [x] Resource drafts, optimistic concurrency, immutable versions and agent releases
- [x] Agent loop with model streaming, tools, budgets, cancellation and checkpoints
- [ ] Execution-time authorization, tool approvals and safe extension boundaries
- [x] Durable runs, ordered events, sessions, artifacts and worker coordination
- [ ] Knowledge ingestion, retrieval, source citations and connection management
- [ ] Evaluations, version comparisons and reviewed improvement suggestions
- [ ] Complete console: setup, dashboard, agents, resources, playground, chat
- [ ] Complete console: runs, knowledge, evaluations, approvals, members, settings
- [ ] Workflow editing and execution with documented supported semantics
- [ ] HTTP/OpenAPI, Python and MCP extension integration
- [ ] Generic SDK examples and two distinct synthetic domain bundles
- [x] Docker/Compose, initial schema bootstrap and deployment instructions
- [ ] README, architecture, API, extension, operations and contribution documentation
- [ ] License, notices, publication inventory and clean export tooling
- [x] Backend contracts/integration tests and frontend build
- [ ] Multi-worker cancellation/recovery, permission and failure-mode verification
- [ ] Clean-machine startup and release artifact verification

## Implementation log

2026-09-20: Created a standalone distribution directory and package skeleton.
Current FarmLynk application code and pre-existing untracked files are untouched.
2026-09-20: Added durable Run worker, workflow baseline execution, knowledge APIs, management console, Docker/Compose and 22 automated tests. Browser E2E, formal migrations, MCP, isolated extension runner and evaluation UI remain open release work.

2026-09-20: Created independent Eivon project in ~/work/eivon. Original scaffold retained.
