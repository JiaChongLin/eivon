# Agent conversations, tools and files

The Playground creates persisted conversations. Select a published Agent, optionally set its business context, and send a message. Every turn is a Run with an immutable Agent release snapshot. A conversation retains its Agent identity and context, while each new turn resolves the Agent's currently active release. The Run inspector shows the selected version and dependencies.

Saved conversations can be reopened after navigation or a browser reload. The transcript comes from persisted Runs; opening a conversation never starts an execution. The model receives up to ten previous completed turns, in chronological order, followed by the new message. Failed and cancelled turns stay visible in the UI but are not included in this model history. The Agent's input-size policy can reject a history that exceeds its budget.

One active or waiting Run is allowed per conversation. The database enforces that invariant, and the composer is disabled until the Run terminates. Start a new conversation for a different Agent or business context. Conversations can run concurrently with each other.

## Instruction composition

Published Agent prompts and Bundle prompts are included once, in dependency order, with literal named variable substitutions. Skills provide a catalog of names, descriptions and exact resource IDs to the model. Preloaded skills include their bodies; other skills expose their method and reference files through `eivon_skill_read`. Neither mechanism selects a business workflow through keyword heuristics.

Business context is serialized as a separate user data message, not appended to system instructions. Domain packages still own data validation and entity-level authorization; this separation does not make arbitrary domain content trusted.

## Execution controls

A model may request multiple tool calls in one response. They execute in order. If a call needs approval, Eivon persists the entire batch and the next-call index. Resuming proceeds from that position, without replaying completed calls or discarding later ones. Each approval applies to the specific call, version and arguments. A repeated resume using the old event sequence fails with a conflict.

The Agent `timeout_seconds` policy limits active execution time across model requests and tool calls. Consumed time is checkpointed; waiting for a person between worker segments does not count. Cancellation propagates to the active async request instead of waiting for a provider's full timeout. Cancelling a remote operation cannot undo an external side effect that already happened.

The same controls are available from Playground and Run history. Status, streamed text events and final output remain visible independently of the browser connection. The browser polls ordered persisted events and deduplicates them by position within a subscription; reopening a Run replays its event history for display only.

## Generated files

Tools such as `export_text` create private artifacts. The Run inspector lists generated files and provides authenticated download links. Both `GET /api/v1/runs/{id}/artifacts` and individual downloads enforce workspace and Run/file ownership; a same-workspace operator cannot read another user's files. Administrators can inspect files in their workspace. Download headers support Unicode filenames.

The list is read after the current Run status, so observing a completed Run does not accidentally freeze an earlier empty artifact listing. File content remains in the configured private data directory and must be backed up with the database.

## Verification and current limits

`tests/test_agent_lifecycle.py` covers a four-call batch with two approval pauses, duplicate resumes, private file delivery, Bundle prompts, skill preload and untrusted context placement. Engine tests cover cancellation and active-time budget exhaustion after checkpoint restoration.

`console/e2e/agent.spec.ts` configures a model, tool and Agent using the real console, approves an export, verifies downloaded bytes and a Unicode filename, continues a second turn, reloads the conversation and cancels an in-flight request. Its HTTP model fixture exists only in the disposable browser test server. It exercises the real compatible-model adapter without real provider credentials. The screenshot in the README was produced by this test and explicitly displays fixture output.

This coverage does not certify production model quality, arbitrary extension safety, high-load operation, or every administration/workspace-switching browser flow. Those remain separate release work.
