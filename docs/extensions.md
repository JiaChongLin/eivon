# Extensions and domain packages

A domain package owns business context schemas, data adapters, tools, skills, workflows and source-specific authorization. It can be installed without modifying `src/eivon/core`.

## Python tool extension

A trusted deployment module exports:

```python
async def register(registry): ...  # register(registry) may be synchronous too
```

`registry.register_tool("entrypoint", async_handler)` registers an async handler. A handler receives a validated argument dictionary and an `ExecutionContext` containing workspace, principal, session, Run and validated business context. Return a `ToolResult`; do not return raw secrets, database connections or unbounded objects.

Create a Tool resource with `adapter: python` and the registered `entrypoint`. Resource publication records the tool schema and Agent releases freeze its version. Runtime authorization and approval are still enforced by Eivon.

## Business context

Use `AgentSpec.context_schema` or a Bundle context schema for domain objects. The core stores the validated object without interpreting it. A domain tool must enforce resource-level authorization using the trusted `ExecutionContext`; an ID supplied in business context is not proof of ownership.

## HTTP adapters

HTTP tools use `config.url`, `config.method` and an optional `credential_id`. The server administrator must allow the destination in `EIVON_OUTBOUND_HOSTS`. Redirects, embedded credentials and secret headers are rejected. Use a domain adapter when the remote service needs pagination, row-level authorization or signed requests.

## MCP and isolated runners

Tool resources with `adapter: mcp` use a Streamable HTTP JSON-RPC `tools/call` request. Set `config.url`, optionally set `config.tool`, and allow the host with `EIVON_OUTBOUND_HOSTS`; credentials and approvals use the same boundary as HTTP tools. Server discovery, stdio transport and isolated extension runners belong in deployment packages. Do not treat deployment-time Python import as a sandbox or expose it to untrusted package authors. See `docs/DELIVERY.md`.
