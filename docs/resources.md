# Resource drafts, releases and rollback

The resource library manages models, embedding providers, prompts, tools, skills, bundles, workflows, Agents and connection configurations. Search by name, filter by type, and use the Active/Archived selector to find resources. Lists are paginated. Archived resources retain their drafts and release history and can be restored.

Resource authors need `write` permission. Readers can inspect specifications, dependencies and differences without editing controls; API mutations independently enforce the same permissions.

## Author a capability

Model creation provides provider, model name, endpoint and encrypted credential selection. Create credentials in Settings; selecting a credential stores its ID, not its value. The deployment's outbound allowlist must permit the provider endpoint before an execution can connect to it.

Embedding resources use the same versioned lifecycle. `provider: local` uses deterministic feature hashing for offline installations; `provider: openai_compatible` calls the bounded `/embeddings` endpoint with an encrypted credential. Knowledge collections pin the embedding resource release used for indexing and querying, and reject searches that combine incompatible releases.

Prompt creation has a template editor. Agent creation selects a published model and optional system prompt. Use the draft JSON editor to configure the rest of the Agent contract, including tools, skills, bundles, knowledge collections and execution policy.

Tools, skills, bundles, workflows and connections have editable JSON specifications at creation. Each type starts with its own valid template, and switching types preserves the separate editor buffers. The server validates the complete specification against the resource contract. The Workflow Studio additionally provides structured editing for all supported step types.

Connection resources store versioned endpoint configuration. Knowledge collections can bind an active connection release and retain that binding while documents are indexed. HTTP connections read bounded JSON feeds; MCP connections read a configured `resource_uri` through `resources/read`. Both paths use the same outbound host, credential, timeout and response-size boundaries. The connection check validates its release and credential scope without sending a network request.

## Save, validate and publish

**Save draft** persists the editor's specification and name using the current optimistic revision. It does not change the active release.

**Validate saved draft** resolves dependencies and checks the saved revision without publishing. Save the editor's changes first. The API accepts an optional `revision`; when provided, validation rejects a stale editor instead of validating a different draft.

**Publish release** includes current editor changes. When the editor is dirty, it saves the draft first and then publishes that exact saved revision. Invalid JSON is rejected without silently reusing an earlier draft. Publishing freezes the specification and dependency snapshot, computes its digest, assigns a new version, and activates that version.

Saving and publishing are two requests when there are edits. If dependency validation or a concurrent edit prevents publication, the successful draft save remains, and the UI reports the publication error. Another user's revision change produces a conflict; the editor retains your local input. **Discard edits and reload** explicitly replaces that buffer with the current saved draft and refreshes release history.

## Inspect and compare

The detail editor shows the active release separately from the latest editable draft. Select a release to inspect its immutable JSON specification, snapshot digest, publication time and pinned dependencies.

Compare it with the current editor draft or another published release. Differences use JSON Pointer paths. Object key order is ignored, arrays retain their order, and additions/removals show a missing-value marker. This is a specification comparison; it does not execute either version or compare model quality.

**Use vN as draft** copies a release's specification into the editor only. Save or publish to persist it. Copying does not activate a release, create a new version or restore an old display name.

## Roll back

Select a previous release and choose **Activate vN**. Activation changes the active-version pointer for future Runs. It does not modify the saved draft, create a release or rewrite any existing Run snapshot. A queued Run continues using its originally selected version. Other resources that already pin a dependency version keep that pin until their own drafts are updated and published.

Activation also advances the optimistic resource revision. A concurrent activation or edit with an older revision is rejected. The UI preserves unsaved draft edits when the activation succeeds.

Rollback restores resource configuration, not database contents, model-provider state, external side effects or a historical secret value. Credentials remain encrypted references managed separately by the deployment.

## Archive and restore

Archive a resource from its detail editor. Save or discard local changes first. It disappears from the default active list, while the Archived list keeps it discoverable. Restore it from the same editor. Drafts, releases and their digests are preserved; archiving prevents new execution/publication of the resource but does not rewrite existing Runs.

## API examples

```http
GET /api/v1/resources?kind=agent&search=assistant&archived=false&offset=0&limit=24
GET /api/v1/resources?archived=true
GET /api/v1/resources/{id}/versions
GET /api/v1/resources/{id}/versions/1
```

`POST /api/v1/resources/{id}/activate`:

```json
{"version": 1, "revision": 4}
```

`POST /api/v1/resources/{id}/archive`:

```json
{"archived": false, "revision": 5}
```

`POST /api/v1/resources/{id}/validate`:

```json
{"revision": 6}
```

## Verified behavior

Backend tests cover archived-list filtering, pagination, workspace isolation, restoration, stale validation, mutation permissions and rollback with real queued workflow Runs. Browser acceptance covers publication of unsaved edits, invalid JSON, release comparisons, activation, copying a version into a draft, archive/restore, concurrent edits, read-only roles and per-type specification buffers. Production load, complete workspace administration and automatic connector integration are still tracked separately in `DELIVERY.md`.
