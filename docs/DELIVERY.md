# Delivery and verification

Source plan: `design/open_source_agent_framework.md`. This checklist preserves the full open-source product scope.

Status: runnable foundation release, still pre-1.0. Completed capabilities and outstanding release work are listed separately; passing the checks below does not establish completion of the full product plan.

- [x] Independent package, CLI and documented installation
- [x] Authentication, workspaces, membership, roles, scoped API keys and audit
- [x] Encrypted credentials and configurable model providers
- [x] Typed tools, skills, prompts, bundles, workflows and extension SDK
- [x] Resource drafts, optimistic concurrency, immutable versions and agent releases
- [x] Agent loop with model streaming, tools, budgets, cancellation and checkpoints
- [x] Execution-time authorization, tool approvals and safe extension boundaries (trusted Python extensions remain deployment-scoped)
- [x] Durable runs, ordered events, sessions, artifacts and worker coordination
- [x] Knowledge ingestion, lexical retrieval and source metadata; semantic citations and connection management remain
- [x] Evaluation sets, batch Runs, deterministic result scoring and release selection; side-by-side version comparison and reviewed improvement suggestions remain
- [x] Complete console: setup, dashboard, agents, resources, playground, chat
- [x] Complete console: runs, knowledge, evaluations, approvals, members, settings (evaluation version comparison remains)
- [x] Workflow execution and structured editor for Input/Tool/Prompt/Condition, typed bindings, schema validation, cancellation, persistent branching and run inspection
- [x] HTTP, trusted Python and Streamable HTTP MCP tool integration
- [x] Generic starter examples and two distinct synthetic domain bundles
- [x] Docker/Compose, versioned schema bootstrap and deployment instructions
- [x] README, architecture, API, extension, operations and contribution documentation
- [x] License, publication inventory and clean export tooling
- [x] Backend contracts/integration tests and frontend build
- [x] Browser acceptance: initialization, workflow authoring, publication, waits, approval, cancellation and Run history
- [x] GitHub Actions configuration for backend/build/browser checks (hosted execution pending publication)
- [x] Multi-worker lease fencing, cancellation/recovery and permission/failure-mode coverage (high-load stress testing remains)
- [x] Clean-machine startup and release artifact verification

## Outstanding release work

- [x] Agent resource authoring, multi-turn chat, file approval/download, conversation recovery and cancellation browser E2E
- [x] Resource publication, comparison, activation rollback, archive/restore, conflicts and read-only role browser E2E
- [x] Workspace switching, create/rename, scoped file delivery and resource/conversation isolation browser E2E
- [ ] Isolated extension runners; Python imports currently remain trusted deployment code
- [ ] Knowledge connection management and semantic retrieval
- [ ] Side-by-side evaluation comparison and reviewed improvement suggestions
- [x] Resource release rollback and immutable version inspection user flows
- [x] Member add/role/remove, credential rotation, API-key issue/revoke and workspace audit user flows
- [ ] High-load stress measurements and production upgrade/restore rehearsal
- [ ] Graph workflow canvas if included in the stable-release scope

## Implementation log

2026-09-20: Created a standalone distribution directory and package skeleton.
Current FarmLynk application code and pre-existing untracked files are untouched.
2026-09-20: Added durable Run worker, workflow baseline execution, knowledge APIs, management console, Docker/Compose and 35 automated tests. Browser E2E, isolated extension runners, version comparisons and production operations hardening remain open release work.
2026-09-20: Added Knowledge and Members console pages plus an approval card in Playground so waiting Runs can be resumed from the UI.
2026-09-20: Added schema migration CLI, persisted evaluation sets/results, evaluation console, MCP Streamable HTTP calls, clean source export tooling and lease-fencing coverage.
2026-09-20: Verified a tracked-file export on a clean temporary directory: schema migration, worker startup, Python wheel build and console install/build all succeeded.
2026-09-20: Added the Workflow Studio for structured input/tool/condition step editing, draft saves and release publishing.

2026-09-20: Created independent Eivon project in ~/work/eivon. Original scaffold retained.

2026-09-20: Corrected workflow branching, empty input resume, per-step models and output templates; added typed bindings, schema validation, in-flight cancellation, full step editing, Run history inspection, six backend regression tests and a browser acceptance flow. Added public CI configuration.

Verification for the workflow completion slice:

- `.venv/bin/pytest -q`: 41 passed (two third-party deprecation warnings).
- `.venv/bin/ruff check src tests scripts examples`: passed.
- `npm run build --prefix console`: passed.
- `EIVON_TEST_CHROME='/Applications/Google Chrome.app/Contents/MacOS/Google Chrome' npm run test:e2e --prefix console`: 1 complete browser acceptance scenario passed; a fresh temporary database/server was used.
- GitHub Actions workflow is committed configuration; a hosted CI run has not been performed because the repository has not been published.

2026-09-20: Fixed Agent batch approval resume and active-time budget enforcement. Published Bundle prompts and skill instructions now enter the model context. Added persisted Playground conversations, private artifact listings and Unicode downloads, plus an Agent browser acceptance scenario and a real console screenshot. Verification: 45 backend tests passed; 2 browser scenarios passed together; frontend build passed. Browser model responses are deterministic fixtures, not live provider verification.

2026-09-20: Added searchable and paginated resource management, archived-resource discovery, per-type authoring buffers, model credential selection, release snapshots and specification comparisons, activation rollback, draft copy and archive/restore. Publication saves the current editor buffer; stale validation/editing is rejected. Added backend rollback/permission tests and browser release-management scenarios.

Resource-management verification: `.venv/bin/pytest -q` passed 48 tests (two dependency deprecation warnings); `.venv/bin/ruff check src tests scripts examples` and `npm run build --prefix console` passed. `EIVON_TEST_CHROME='/Applications/Google Chrome.app/Contents/MacOS/Google Chrome' npm run test:e2e --prefix console` passed all 5 browser scenarios together against the disposable server. No hosted CI or live connector execution was claimed by these checks.

2026-09-20: Added workspace selection/create/rename, member role/removal controls, credential rotation, configurable API key expiry/permissions/revocation and paginated audit inspection. Console requests and generated-file downloads carry explicit workspace scope; switching resets page state and cancels pending requests. API-key identity lists only its own workspace. Removed members can discover session CSRF and sign out without workspace access.

Workspace-administration verification: `.venv/bin/pytest -q` passed 51 tests (two dependency deprecation warnings and a non-failing cache write warning in the restricted test invocation); `RUFF_CACHE_DIR=/tmp/eivon-ruff .venv/bin/ruff check src tests scripts examples` and `npm run build --prefix console` passed. `EIVON_TEST_CHROME='/Applications/Google Chrome.app/Contents/MacOS/Google Chrome' npm run test:e2e --prefix console` passed all 7 browser scenarios against a disposable server, including non-default-workspace Unicode file download, resource/conversation isolation and membership removal. Hosted CI and live provider checks remain unperformed.
