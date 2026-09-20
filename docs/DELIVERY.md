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
- [x] Knowledge ingestion, connection bindings, bounded JSON synchronization, source metadata and lexical/semantic/hybrid retrieval; connector-specific adapters and provider embeddings remain
- [x] Evaluation sets, historical batches, deterministic scoring, human reviews, version comparison, model-generated failure analysis and reviewed instruction candidates
- [x] Complete console: setup, dashboard, agents, resources, playground, chat
- [x] Complete console: runs, knowledge, evaluations, model analysis, approvals, members, settings
- [x] Workflow execution and structured editor for Input/Tool/Prompt/Condition, typed bindings, schema validation, cancellation, persistent branching and run inspection
- [x] HTTP, trusted Python and Streamable HTTP MCP tool integration
- [x] Generic starter examples and two distinct synthetic domain bundles
- [x] Docker/Compose, versioned schema bootstrap and deployment instructions
- [x] README, architecture, API, extension, operations and contribution documentation
- [x] License, publication inventory and clean export tooling
- [x] Backend contracts/integration tests and frontend build
- [x] Browser acceptance: initialization, workflow authoring, publication, waits, approval, cancellation and Run history
- [x] GitHub Actions configuration for backend/build/browser checks (hosted execution pending publication)
- [x] Multi-worker lease fencing, cancellation/recovery, permission/failure-mode coverage and repeatable high-load SQLite stress evidence
- [x] Clean-machine startup and release artifact verification

## Outstanding release work

- [x] Agent resource authoring, multi-turn chat, file approval/download, conversation recovery and cancellation browser E2E
- [x] Resource publication, comparison, activation rollback, archive/restore, conflicts and read-only role browser E2E
- [x] Workspace switching, create/rename, scoped file delivery and resource/conversation isolation browser E2E
- [x] Optional isolated Python extension runner with JSON boundary, timeout and cancellation termination; OS sandboxing remains deployment-owned
- [x] Knowledge connection binding, connection checks and semantic/hybrid retrieval
- [x] Bounded generic JSON knowledge synchronization with source metadata and digest deduplication
- [x] Provider-managed embeddings through versioned resources; connector-specific sync adapters remain
- [x] Side-by-side evaluation comparison, failure evidence, human scoring and reviewed instruction candidates
- [ ] Model-generated failure analysis and instruction suggestions
- [x] Resource release rollback and immutable version inspection user flows
- [x] Member add/role/remove, credential rotation, API-key issue/revoke and workspace audit user flows
- [x] High-load SQLite stress measurements
- [ ] Production PostgreSQL upgrade/restore rehearsal
- [x] Workflow graph view for the ordered executor and conditional skip edges

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

2026-09-20: Replaced the latest-result-only evaluation view with paginated batch history, exact-batch case inspection and side-by-side release comparison. Added append-only human scores, failure-evidence summaries and Prompt/Skill instruction candidates. Administrator acceptance checks the frozen draft revision and applies the draft update and review transition atomically; published resources and permissions remain unchanged. Added schema v4 additive tables and rejected future schema versions before DDL. Model-generated causal analysis and suggestions are explicitly still pending.

Evaluation-center verification: `.venv/bin/pytest -q` passed 56 tests (two dependency deprecation warnings); after strengthening the scoped-key authorization assertion, `.venv/bin/pytest -q tests/test_evaluation_review.py` passed all 5 targeted tests. `.venv/bin/ruff check src tests scripts examples`, `npm run build --prefix console` and `git diff --check` passed. `EIVON_TEST_CHROME='/Applications/Google Chrome.app/Contents/MacOS/Google Chrome' npm run test:e2e --prefix console` passed all 8 browser scenarios, including historical batch comparison, independent human scoring, accepted-draft persistence and immutable published instructions. Inspected the rendered evaluation-center screenshot. Tests used SQLite and deterministic/demo model responses; PostgreSQL upgrade rehearsal, live-model quality validation and hosted CI are not claimed.

2026-09-20: Added versioned connection bindings for Knowledge collections, connection configuration checks, deterministic offline embeddings and lexical/semantic/hybrid retrieval scores. Search results preserve source URI, collection, lexical score and semantic score; collection and connection access remain workspace-scoped. Added Knowledge console controls and browser coverage.

Knowledge verification: `.venv/bin/pytest -q tests/test_knowledge.py` passed 3 tests; full suite and browser verification follow this change. Semantic retrieval is a deterministic local embedding baseline for self-hosted/offline installs, not a claim of model-quality vector search. Remote connector synchronization and provider-managed embedding models remain optional future extensions.

Knowledge verification final: `.venv/bin/pytest -q` passed 58 tests; `npm run build --prefix console` passed; `EIVON_TEST_CHROME='/Applications/Google Chrome.app/Contents/MacOS/Google Chrome' npm run test:e2e --prefix console` passed all 9 browser scenarios. The disposable browser server covered connection binding, source metadata and semantic/lexical search. The repository remains pre-1.0: remote synchronization, provider-managed embeddings, isolated extension runners, high-load measurements and production restore rehearsal remain explicit follow-up work.


2026-09-20: Added `EIVON_EXTENSION_RUNNER=process`. Process mode avoids importing extension modules in the worker, starts one short-lived child per Python tool call, validates an ExecutionContext/ToolResult JSON protocol, and terminates the process group on timeout or cancellation. The default trusted mode remains available; deployment-level OS sandboxing is still required for hostile code.

Extension verification: `.venv/bin/pytest -q` passed 60 tests; extension-specific execution and timeout tests passed; `npm run build --prefix console` passed; all 9 browser scenarios passed after the change.

2026-09-20: Added generic Knowledge synchronization. A bound connection can GET a bounded JSON document feed, validate the deployment allowlist and credentials, preserve source URIs, compute local embeddings and skip duplicate content by digest. The console exposes Sync connection for bound collections.

Knowledge synchronization verification: `.venv/bin/pytest -q` passed 61 tests; knowledge sync, connection scope and deduplication tests passed; `npm run build --prefix console` passed; all 9 browser scenarios passed. The sync contract is intentionally generic and does not claim connector-specific pagination, webhooks or provider-managed embedding quality.

2026-09-20: Added `eivon backup` and `eivon restore --force`. SQLite archives use the online backup API and include artifacts plus a schema manifest; restore rejects unsafe paths and future schemas. PostgreSQL backup delegates to `pg_dump --format=custom`, and restore delegates to a guarded `pg_restore` command.

Backup verification: `.venv/bin/pytest -q` passed 63 tests; `npm run build --prefix console` passed; all 9 browser scenarios passed. SQLite round-trip and unsafe archive tests passed. PostgreSQL production restore rehearsal remains open.

2026-09-20: Added `scripts/stress_leases.py` and a regression test for concurrent run claiming. Eight independent SQLite database connections claimed 128 queued runs with zero duplicate claims or worker errors (0.1382 seconds, 926.27 claims/second on the development machine). The same run then rejected a stale claim, heartbeat and finish from the old worker and was terminalized as `failed` with the side-effect warning.

Stress verification: `PYTHONPATH=src .venv/bin/python scripts/stress_leases.py --runs 128 --workers 8` produced `claims=128`, `unique_claims=128`, `duplicate_claims=0`, and all fencing assertions true; the full regression test covers the same invariants. PostgreSQL production upgrade/restore rehearsal remains open.

2026-09-20: Added `POST /evaluation-jobs/{id}/analysis`. It invokes the model pinned by the evaluated Agent release, preserves bounded raw output, accepts structured failure patterns and suggestions when the provider returns JSON, and stores the result on the immutable evaluation batch without changing resources. The console exposes model analysis beside the human proposal review flow.

2026-09-20: Added schema v6 versioned `embedding` resources. Collections pin an embedding release; local feature hashing remains the offline default and OpenAI-compatible `/embeddings` is bounded, allowlisted, credential-aware and dimension-validated. Search rejects collections with incompatible embedding fingerprints.

Analysis and embedding verification: `.venv/bin/pytest -q tests/test_evaluation_review.py tests/test_knowledge.py tests/test_backup.py` passed 13 tests; provider calls use deterministic mocked responses and no real credentials.

2026-09-20: Added a Workflow Studio graph view that renders ordered Input, Tool, Prompt and Condition nodes plus conditional skip edges. The existing step editor remains the source of truth; the graph is an inspection and navigation view, not a claim of arbitrary parallel graph execution.

Graph verification: the workflow browser acceptance now switches to Graph view, verifies rendered nodes, returns to Step editor, and completes the existing publish, wait, approval, cancellation and Run inspection flow.
