# Workflow authoring and execution

Open **Workflows** to create a workflow. Define an input schema and output template, add ordered steps, then **Save and publish**. Tool and Prompt steps pin an explicit published version of a tool or model. Selecting a different resource selects its active release; the version field can select an older published release. Publishing checks that every dependency exists in the current workspace. Switch between **Step editor** and **Graph view** to inspect the same draft; the graph shows ordered execution and conditional skip edges.

The editor preserves the full supported workflow contract, including Prompt steps, JSON comparison values, per-step response schemas and output templates. JSON fields retain incomplete edits while typing; saving invalid JSON fails without silently using older values. A publication refreshes the draft revision so the next save remains valid. Publishing includes current editor changes; running always uses the selected published version, never unsaved edits.

## Steps

- **Input** pauses with a question and JSON Schema. The submitted object becomes `steps.<id>`. An empty object is a valid response if the schema permits it. Resume includes the Run's current event sequence, so submitting the same response twice cannot advance twice.
- **Tool** resolves argument bindings and invokes the pinned tool through the shared validation, permission and approval boundary. `steps.<id>` contains the ToolResult, including `success`, `data` and `error`. A failed ToolResult is available to later condition steps; it does not automatically stop the workflow.
- **Prompt** resolves its template and calls its own pinned model. `steps.<id>` contains `text` and `usage`. Prompt steps do not offer tools to the model; use explicit Tool steps for effects. Cancellation interrupts an in-flight call, and the model timeout bounds its duration.
- **Condition** compares a path's JSON value with `equals`. A match skips the selected later step IDs, even when they are noncontiguous. Skipped steps have no result. The condition itself produces `{ "matched": true|false }`. Boolean values are distinct from numbers; numeric `1` and `1.0` compare equally. Skip decisions persist through input and approval pauses and worker changes.

Only later steps can be skipped. This is an ordered workflow with conditional skips; cycles, arbitrary graph edges, parallel branches and nested workflow invocation are not supported by this executor.

## Bindings

Paths start with `input`, `context` or `steps`. Dot-separated segments access JSON object keys or array indexes, without expression evaluation, attribute access or code execution.

```json
{
  "customer": "{{input.customer}}",
  "count": "{{steps.lookup.data.count}}",
  "message": "Found {{steps.lookup.data.count}} matches",
  "first": "{{input.items.0}}"
}
```

A whole placeholder preserves the value's JSON type, including booleans, arrays and objects. An embedded placeholder converts its value to text. Replacement values are not recursively interpreted as templates. Missing paths fail the Run before the affected tool is invoked. Keys containing dots cannot be addressed using this syntax.

Prompt and output templates always produce text. The default output template is `{{steps}}`; the Run also returns a structured `output.steps` object independently of the selected output template.

## Run and recover

`POST /api/v1/runs` accepts a workflow input object:

```json
{
  "resource_id": "published-workflow-id",
  "version": 1,
  "input": {"customer": "demo", "items": [1, 2]},
  "context": {"team": "support"}
}
```

The server validates `input` against the published workflow input schema before queueing. For existing callers omitting `input`, the workflow input defaults to `{"message": "<message argument>"}`. `context` is kept separate from the workflow input and is available to trusted domain adapters.

The Studio run panel and **Run history** both show status, output, dependency versions and the event timeline. They accept input, approve or decline waiting tool calls, and cancel Runs. Opening an existing Run does not create or restart execution. Polling stops on terminal or waiting states and resumes after a user action; leaving the page aborts outstanding requests.

A resumed workflow restores its next step, prior results, skipped IDs and approval decisions from persisted state. A worker lease lost while actively performing a side effect is still handled conservatively by the shared Run service; Eivon does not promise exactly-once external effects.

## Validation

`tests/test_workflows.py` exercises schema validation, typed bindings, noncontiguous branching across worker replacement, empty response resume, per-step models, missing bindings and in-flight cancellation.

The Playwright workflow acceptance test starts an isolated disposable server, initializes a workspace through the browser, seeds synthetic tool/model releases through the API, and uses the UI to author, validate, publish, edit, run, resume, approve, cancel and inspect a workflow. It is offline and makes no model-provider calls. It does not yet replace the remaining Agent/chat, artifact and administration E2E coverage.
