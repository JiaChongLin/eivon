# Evaluations, human review and instruction improvements

Use **Evaluations** to save an immutable test set, run it against a published Agent version, inspect historical batches and compare two releases. The worker persists each case as a Run with a frozen dependency snapshot. Results are tied to a specific batch, so opening an older batch never substitutes the newest result.

## Test cases and scores

A test set contains 1–500 cases:

```json
[
  {"input": "Summarize this text", "context": {}, "expected": "summary", "match": "contains"},
  {"input": "Return a greeting", "expected": "Hello", "match": "exact"},
  {"input": "Explain the process", "match": "nonempty"}
]
```

`contains` is case-insensitive and requires nonempty expected text. `exact` compares trimmed strings. `nonempty` checks for non-whitespace output. A failed or timed-out execution receives zero. Batch rule score is the mean across cases; these checks measure the specified condition and are not a claim about general answer quality.

An author can append a human score from 0 to 1 and a review note on an individual case. Human reviews retain the reviewer ID and timestamp. They do not rewrite the automatic score or its aggregate, and earlier reviews remain visible.

## Version comparison

Select a baseline and candidate from completed batches of the same Agent and test set. The API also checks the saved test-set revision and exact case snapshots. The result shows the expected text, both outputs/statuses, per-case rule-score changes, improvement/regression counts and aggregate score delta. Human reviews appear alongside their corresponding output.

The history API is paginated and filters by test set before pagination. Administrators can read all evaluation batches in their current workspace; other members see only their own Runs and batches. Cross-workspace requests cannot read another workspace's results, reflection or proposals.

## Reflection and reviewed candidates

A completed batch provides a factual reflection report: failing cases, expected and actual outputs, statuses and links to the Runs. This is an evidence summary, not model-generated causal reasoning.

The improvement form lets an author choose a Prompt or Skill dependency used by the evaluated release and submit replacement instructions with a rationale. It starts from that resource's **current draft**, which can differ from its evaluated release. A proposal freezes the draft revision, before/after specifications, submitter and evaluation batch. It can change only Prompt `template` or Skill `body`; it cannot change tool permissions, reference bindings or policies.

An administrator reviews the full before/after content and either rejects the candidate or accepts it into the draft. Accepting also requires `write` permission for scoped API keys. The proposal transition and draft update commit together. Concurrent edits, archival or unavailable dependencies prevent application and leave the proposal pending. A reviewed proposal cannot be applied a second time.

Acceptance does not publish the resource or change an active release. To measure the change:

1. Inspect and publish the updated Prompt/Skill draft in Resources.
2. Update the Agent's dependency reference (or its Bundle/Skill dependency chain) and publish a new Agent version.
3. Rerun the same test set and compare its new batch with the baseline.

Candidates are authored by a person in this release. Automatic model-generated suggestions remain future work; no improvement is claimed until a subsequent evaluation supplies evidence.

## API

All routes below are under `/api/v1` and use the current workspace scope.

| Route | Behavior |
| --- | --- |
| `POST /evaluations` | Save an immutable test set |
| `POST /evaluations/{id}/run` | Run a published Agent version; return durable Job |
| `GET /evaluations/{id}/jobs?offset=0&limit=25` | Paginated batch history |
| `GET /evaluation-jobs/{id}` | Exact batch input, aggregate and case results with human reviews |
| `GET /evaluation-comparison?baseline={id}&candidate={id}` | Compare compatible completed batches |
| `POST /evaluation-jobs/{id}/results/{result_id}/reviews` | Append `{ "score": 0.5, "note": "…" }` |
| `GET /evaluation-jobs/{id}/reflection` | Failure evidence, editable instruction targets and proposals |
| `POST /evaluation-jobs/{id}/proposals` | Submit `{ "resource_id": "…", "revision": 3, "text": "…", "rationale": "…" }` |
| `POST /evaluation-jobs/{id}/proposals/{proposal_id}/review` | Decide with `{ "decision": "accepted", "note": "…" }` or `rejected` |

Schema version 4 adds `evaluation_reviews` and `improvement_proposals` without changing existing evaluation results. Back up the database before deployment upgrades; `eivon migrate` applies the additive upgrade. Newer unknown schema versions are rejected before schema changes.

The current improvement flow is intentionally human-authored: Eivon records failure evidence and applies only a reviewed candidate. A future extension may generate candidate text, but it must enter the same pending review state and rerun the test set before release.
