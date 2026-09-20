"""Snapshot-scoped tool execution with uniform validation, approval and budgets."""

from __future__ import annotations

import ast
import asyncio
import hashlib
import json
import math
import operator
from datetime import UTC, datetime

import httpx
from jsonschema import Draft202012Validator

from eivon.adapters.mcp import McpError
from eivon.adapters.mcp import call_http as call_mcp_http
from eivon.adapters.network import check_destination
from eivon.core.contracts import ExecutionContext, ToolCall, ToolResult, ToolSpec
from eivon.core.engine import PauseExecution
from eivon.core.extensions import ExtensionRegistry

from .artifacts import Artifacts
from .resources import canonical
from .security import Security
from .settings import Settings


def tool_name(resource: dict) -> str:
    return "tool_" + resource["id"][:24]


def calculate(expression: str) -> float:
    if len(expression) > 200:
        raise ValueError("Expression is too long")
    ops = {
        ast.Add: operator.add,
        ast.Sub: operator.sub,
        ast.Mult: operator.mul,
        ast.Div: operator.truediv,
        ast.USub: operator.neg,
        ast.UAdd: operator.pos,
        ast.Mod: operator.mod,
    }

    def evaluate(node, depth=0):
        if depth > 20:
            raise ValueError("Expression is too complex")
        if isinstance(node, ast.Constant) and type(node.value) in {int, float}:
            value = node.value
        elif isinstance(node, ast.BinOp) and type(node.op) in ops:
            value = ops[type(node.op)](
                evaluate(node.left, depth + 1), evaluate(node.right, depth + 1)
            )
        elif isinstance(node, ast.UnaryOp) and type(node.op) in ops:
            value = ops[type(node.op)](evaluate(node.operand, depth + 1))
        else:
            raise ValueError("Only numeric arithmetic is supported")
        if not math.isfinite(value) or abs(value) > 1e15:
            raise ValueError("Result exceeds calculator limits")
        return value

    return evaluate(ast.parse(expression, mode="eval").body)


class ToolRuntime:
    def __init__(
        self,
        *,
        snapshot: dict,
        context: ExecutionContext,
        settings: Settings,
        security: Security,
        artifacts: Artifacts,
        extensions: ExtensionRegistry,
        decisions: dict | None = None,
        require_write_approval: bool = True,
        emit=None,
        knowledge_search=None,
    ):
        self.snapshot, self.context, self.settings = snapshot, context, settings
        self.security, self.artifacts, self.extensions = security, artifacts, extensions
        self.decisions = decisions if decisions is not None else {}
        self.require_write_approval = require_write_approval
        self.emit, self.knowledge_search = emit, knowledge_search
        resources = list(snapshot.get("resources", {}).values())
        if snapshot["root"]["kind"] == "tool":
            resources.append(snapshot["root"])
        self.tools = {tool_name(r): r for r in resources if r["kind"] == "tool"}
        self.skills = {r["id"]: r for r in resources if r["kind"] == "skill"}

    def definitions(self) -> list[dict]:
        tools = [
            {
                "type": "function",
                "function": {
                    "name": name,
                    "description": f"{r['name']}: {r['spec']['description']}",
                    "parameters": r["spec"]["input_schema"],
                },
            }
            for name, r in self.tools.items()
        ]
        if self.skills:
            tools.append(
                {
                    "type": "function",
                    "function": {
                        "name": "eivon_skill_read",
                        "description": "Read a skill's full method or a named reference before using its domain instructions.",
                        "parameters": {
                            "type": "object",
                            "properties": {
                                "skill_id": {"type": "string", "enum": list(self.skills)},
                                "reference": {"type": "string"},
                            },
                            "required": ["skill_id"],
                            "additionalProperties": False,
                        },
                    },
                }
            )
        if self.snapshot.get("knowledge_collection_ids") and self.knowledge_search:
            tools.append(
                {
                    "type": "function",
                    "function": {
                        "name": "eivon_knowledge_search",
                        "description": "Search the Agent's authorized knowledge collections. Cite source document and chunk IDs.",
                        "parameters": {
                            "type": "object",
                            "properties": {
                                "query": {"type": "string", "minLength": 1, "maxLength": 2000}
                            },
                            "required": ["query"],
                            "additionalProperties": False,
                        },
                    },
                }
            )
        return tools

    async def invoke(self, call: ToolCall) -> ToolResult:
        definitions = {d["function"]["name"]: d["function"] for d in self.definitions()}
        definition = definitions.get(call.name)
        if definition is None:
            return ToolResult(success=False, error="Tool is not authorized in this Agent release")
        errors = list(Draft202012Validator(definition["parameters"]).iter_errors(call.arguments))
        if errors:
            return ToolResult(
                success=False, error="Tool arguments failed validation: " + errors[0].message[:500]
            )
        if call.name == "eivon_skill_read":
            skill = self.skills.get(call.arguments["skill_id"])
            if skill is None:
                return ToolResult(success=False, error="Skill is not available in this release")
            reference = call.arguments.get("reference")
            content = (
                skill["spec"]["references"].get(reference) if reference else skill["spec"]["body"]
            )
            if content is None:
                return ToolResult(success=False, error="Skill reference not found")
            if self.emit:
                await self.emit(
                    "skill.loaded",
                    {"skill_id": skill["id"], "version": skill["version"], "reference": reference},
                )
            return ToolResult(
                success=True,
                data={"content": content[:60_000], "references": list(skill["spec"]["references"])},
                completeness="truncated" if len(content) > 60_000 else "complete",
            )
        if call.name == "eivon_knowledge_search":
            hits = self.knowledge_search(
                self.context.workspace_id,
                self.snapshot["knowledge_collection_ids"],
                call.arguments["query"],
            )
            return ToolResult(
                success=True, data={"hits": hits}, completeness="complete" if hits else "empty"
            )
        resource = self.tools[call.name]
        spec = ToolSpec.model_validate(resource["spec"])
        approval_key = hashlib.sha256(
            canonical(
                {
                    "call_id": call.id,
                    "resource": resource["id"],
                    "version": resource.get("version", 0),
                    "arguments": call.arguments,
                }
            ).encode()
        ).hexdigest()
        if spec.requires_approval or (spec.effect == "write" and self.require_write_approval):
            if approval_key not in self.decisions:
                raise PauseExecution(
                    "waiting_approval",
                    {
                        "approval_key": approval_key,
                        "call_id": call.id,
                        "tool": resource["name"],
                        "arguments": call.arguments,
                        "effect": spec.effect,
                    },
                )
            if not self.decisions[approval_key]:
                return ToolResult(
                    success=False, error="Tool execution was declined by the operator"
                )
        try:
            async with asyncio.timeout(spec.timeout_seconds):
                result = await self._execute(spec, call.arguments)
            if spec.output_schema and not Draft202012Validator(spec.output_schema).is_valid(
                result.data
            ):
                return ToolResult(success=False, error="Tool output failed its declared schema")
            encoded = result.model_dump_json().encode()
            if len(encoded) > spec.max_result_bytes:
                return ToolResult(
                    success=result.success,
                    data={
                        "preview": encoded[: spec.max_result_bytes // 2].decode(errors="replace"),
                        "original_bytes": len(encoded),
                    },
                    completeness="truncated",
                    artifacts=result.artifacts[:10],
                )
            return result
        except TimeoutError:
            return ToolResult(
                success=False, error="Tool timed out; external side effects may have completed"
            )
        except (ValueError, ZeroDivisionError, SyntaxError) as exc:
            return ToolResult(success=False, error=str(exc)[:500])
        except Exception as exc:
            return ToolResult(
                success=False,
                error=f"Tool failed ({type(exc).__name__}); inspect the connector configuration",
            )

    async def _execute(self, spec: ToolSpec, arguments: dict) -> ToolResult:
        if spec.adapter == "builtin":
            if spec.entrypoint == "echo":
                return ToolResult(success=True, data=arguments)
            if spec.entrypoint == "clock":
                return ToolResult(success=True, data={"utc": datetime.now(UTC).isoformat()})
            if spec.entrypoint == "calculator":
                return ToolResult(
                    success=True, data={"value": calculate(str(arguments.get("expression", "")))}
                )
            if spec.entrypoint == "export_text":
                content = str(arguments.get("content", ""))
                artifact = self.artifacts.create(
                    self.context.workspace_id,
                    self.context.principal_id,
                    self.context.run_id,
                    str(arguments.get("name", "document.md")),
                    "text/plain; charset=utf-8",
                    content.encode(),
                )
                return ToolResult(success=True, data={"artifact": artifact}, artifacts=[artifact])
            raise ValueError("Unknown builtin tool")
        if spec.adapter == "python":
            return await self.extensions.invoke(
                spec.entrypoint, arguments, self.context, spec.timeout_seconds
            )
        if spec.adapter == "http":
            url = check_destination(str(spec.config["url"]), self.settings.allowed_hosts)
            method = str(spec.config.get("method", "GET")).upper()
            if method not in {"GET", "POST", "PUT", "PATCH", "DELETE"}:
                raise ValueError("Unsupported HTTP method")
            if method != "GET" and spec.effect != "write":
                raise ValueError("Non-GET HTTP tools must declare effect=write")
            headers = dict(spec.config.get("headers", {}))
            secret = self.security.credential_value(self.context.workspace_id, spec.credential_id)
            if secret:
                headers["Authorization"] = "Bearer " + secret
            kwargs = {"params": arguments} if method == "GET" else {"json": arguments}
            async with httpx.AsyncClient(
                timeout=spec.timeout_seconds, trust_env=False, follow_redirects=False
            ) as client:
                async with client.stream(method, url, headers=headers, **kwargs) as response:
                    if response.status_code >= 300:
                        return ToolResult(
                            success=False, error=f"Connector returned HTTP {response.status_code}"
                        )
                    buffer = bytearray()
                    async for part in response.aiter_bytes():
                        buffer.extend(part)
                        if len(buffer) > spec.max_result_bytes:
                            return ToolResult(
                                success=True,
                                data={
                                    "preview": bytes(buffer[: spec.max_result_bytes // 2]).decode(
                                        errors="replace"
                                    )
                                },
                                completeness="truncated",
                            )
                    text = bytes(buffer).decode(errors="replace")
                    if secret:
                        text = text.replace(secret, "[REDACTED]")
                    try:
                        data = json.loads(text)
                    except json.JSONDecodeError:
                        data = {"text": text}
                    return ToolResult(success=True, data=data)
        if spec.adapter == "mcp":
            url = check_destination(str(spec.config["url"]), self.settings.allowed_hosts)
            tool = str(spec.config.get("tool", spec.entrypoint))
            secret = self.security.credential_value(self.context.workspace_id, spec.credential_id)
            headers = dict(spec.config.get("headers", {}))
            if secret:
                headers["Authorization"] = "Bearer " + secret
            try:
                data = await call_mcp_http(
                    url,
                    tool,
                    arguments,
                    self.settings.allowed_hosts,
                    headers=headers,
                    timeout=spec.timeout_seconds,
                    max_response_bytes=spec.max_result_bytes,
                )
            except McpError as exc:
                return ToolResult(success=False, error=str(exc))
            if secret:
                data = _redact(data, secret)
            return ToolResult(success=True, data=data)
        raise ValueError("Unknown tool adapter")


def _redact(value, secret: str):
    if isinstance(value, str):
        return value.replace(secret, "[REDACTED]")
    if isinstance(value, list):
        return [_redact(item, secret) for item in value]
    if isinstance(value, dict):
        return {key: _redact(item, secret) for key, item in value.items()}
    return value
