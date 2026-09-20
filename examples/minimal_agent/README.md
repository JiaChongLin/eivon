# Minimal Agent

This example shows the smallest Eivon resource graph:

1. create and publish a `model` (`provider: demo` for offline use);
2. create and publish a `prompt`;
3. create an `agent` whose `model_ref` and `prompt_refs` point at those versions;
4. create a Run through `/api/v1/runs`.

The management console performs these steps interactively. The example deliberately has no business vocabulary, database schema or industry dependency.
