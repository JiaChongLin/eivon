"""Bounded MCP Streamable HTTP sessions for explicitly configured tools.

Supports the 2025-06-18 and 2025-03-26 protocol versions. Each call negotiates
its own session; uncertain calls are never retried automatically.
"""

from __future__ import annotations

import asyncio
import codecs
import json
import uuid
from contextlib import suppress
from typing import Any

import httpx

from .network import check_destination

SUPPORTED_VERSIONS = ("2025-06-18", "2025-03-26")


class McpError(ValueError):
    pass


def _message(value: str | bytes) -> dict[str, Any]:
    try:
        payload = json.loads(value)
    except (ValueError, UnicodeError) as exc:
        raise McpError("MCP server returned invalid JSON") from exc
    if not isinstance(payload, dict) or payload.get("jsonrpc") != "2.0":
        raise McpError("MCP server returned an invalid JSON-RPC message")
    return payload


def _result(payload: dict[str, Any], request_id: str) -> dict[str, Any] | None:
    if payload.get("id") != request_id:
        if "id" not in payload and isinstance(payload.get("method"), str):
            return None  # Server notifications may precede the response.
        raise McpError("MCP response does not match the request")
    if "error" in payload:
        # Remote error strings can contain credentials or arbitrary connector data.
        raise McpError("MCP server rejected the request")
    if not isinstance(payload.get("result"), dict):
        raise McpError("MCP response did not contain a result object")
    return payload["result"]


async def _read(response: httpx.Response, request_id: str, max_bytes: int) -> dict:
    content_type = response.headers.get("content-type", "").split(";", 1)[0].strip().lower()
    if content_type not in {"application/json", "text/event-stream"}:
        raise McpError("MCP response requires JSON or SSE content type")
    size = 0
    buffer = bytearray()
    decoder = codecs.getincrementaldecoder("utf-8")()
    pending = ""
    data_lines: list[str] = []
    async for part in response.aiter_bytes():
        size += len(part)
        if size > max_bytes:
            raise McpError("MCP response exceeds its configured byte limit")
        if content_type == "application/json":
            buffer.extend(part)
            continue
        try:
            pending += decoder.decode(part)
        except UnicodeError as exc:
            raise McpError("MCP stream is not UTF-8") from exc
        while "\n" in pending:
            line, pending = pending.split("\n", 1)
            line = line.rstrip("\r")
            if not line:
                if data_lines:
                    result = _result(_message("\n".join(data_lines)), request_id)
                    if result is not None:
                        return result
                    data_lines.clear()
            elif line.startswith("data:"):
                value = line[5:]
                data_lines.append(value[1:] if value.startswith(" ") else value)
    if content_type == "application/json":
        result = _result(_message(bytes(buffer)), request_id)
        if result is not None:
            return result
    raise McpError("MCP stream ended before a matching response")


def extract_result(result: dict[str, Any]) -> Any:
    if result.get("isError"):
        raise McpError("MCP server rejected the tool call")
    if "structuredContent" in result:
        return result["structuredContent"]
    # Preserve non-text content and resource links for the caller's result schema.
    content = result.get("content", [])
    if not isinstance(content, list):
        raise McpError("MCP tool result has invalid content")
    return {
        "content": content,
        "text": "\n".join(
            item["text"]
            for item in content
            if isinstance(item, dict)
            and item.get("type") == "text"
            and isinstance(item.get("text"), str)
        ),
    }


async def call_http(
    url: str,
    tool: str,
    arguments: dict[str, Any],
    allowed_hosts: tuple[str, ...],
    headers: dict[str, str] | None = None,
    timeout: int = 30,
    transport: httpx.AsyncBaseTransport | None = None,
    max_response_bytes: int = 1_048_576,
    rpc_method: str = "tools/call",
    rpc_params: dict[str, Any] | None = None,
    required_capability: str = "tools",
) -> Any:
    endpoint = check_destination(url, allowed_hosts)
    request_headers = httpx.Headers(headers or {})
    request_headers["Content-Type"] = "application/json"
    request_headers["Accept"] = "application/json, text/event-stream"
    # Protocol/session headers are negotiated, never accepted from tool config.
    for name in ("Mcp-Session-Id", "MCP-Protocol-Version"):
        request_headers.pop(name, None)
    async with httpx.AsyncClient(
        timeout=timeout, trust_env=False, follow_redirects=False, transport=transport
    ) as client:

        async def request(method: str, params: dict) -> tuple[dict, str | None]:
            request_id = uuid.uuid4().hex
            async with client.stream(
                "POST",
                endpoint,
                headers=request_headers,
                json={"jsonrpc": "2.0", "id": request_id, "method": method, "params": params},
            ) as response:
                if response.status_code != 200:
                    raise McpError(
                        f"MCP server returned HTTP {response.status_code}; call was not retried"
                    )
                session = response.headers.get("Mcp-Session-Id")
                return await _read(response, request_id, max_response_bytes), session

        try:
            async with asyncio.timeout(timeout):
                initialized, session = await request(
                    "initialize",
                    {
                        "protocolVersion": SUPPORTED_VERSIONS[0],
                        "capabilities": {},
                        "clientInfo": {"name": "eivon", "version": "0.1.0"},
                    },
                )
                if session:
                    if len(session) > 1024 or any(not 0x21 <= ord(c) <= 0x7E for c in session):
                        raise McpError("MCP server returned an invalid session ID")
                    request_headers["Mcp-Session-Id"] = session
                version = initialized.get("protocolVersion")
                if version not in SUPPORTED_VERSIONS:
                    raise McpError("MCP server selected an unsupported protocol version")
                capabilities = initialized.get("capabilities")
                if not isinstance(capabilities, dict) or required_capability not in capabilities:
                    raise McpError(f"MCP server did not advertise {required_capability} capability")
                request_headers["MCP-Protocol-Version"] = version
                async with client.stream(
                    "POST",
                    endpoint,
                    headers=request_headers,
                    json={"jsonrpc": "2.0", "method": "notifications/initialized"},
                ) as response:
                    if response.status_code != 202:
                        raise McpError("MCP server did not accept initialization notification")
                params = rpc_params if rpc_params is not None else {"name": tool, "arguments": arguments}
                result, _ = await request(rpc_method, params)
                return extract_result(result) if rpc_method == "tools/call" else result
        finally:
            if request_headers.get("Mcp-Session-Id"):
                with suppress(httpx.HTTPError, TimeoutError):
                    async with asyncio.timeout(2):
                        async with client.stream("DELETE", endpoint, headers=request_headers):
                            pass


async def read_resource(
    url: str,
    uri: str,
    allowed_hosts: tuple[str, ...],
    headers: dict[str, str] | None = None,
    timeout: int = 30,
    transport: httpx.AsyncBaseTransport | None = None,
    max_response_bytes: int = 5_000_000,
) -> dict[str, Any]:
    """Read a JSON resource from an MCP server using the standard resources/read method."""
    result = await call_http(
        url,
        "",
        {},
        allowed_hosts,
        headers=headers,
        timeout=timeout,
        transport=transport,
        max_response_bytes=max_response_bytes,
        rpc_method="resources/read",
        rpc_params={"uri": uri},
        required_capability="resources",
    )
    if not isinstance(result.get("contents"), list):
        raise McpError("MCP resource result has invalid contents")
    return result
