import json

import httpx
import pytest

from eivon.adapters.mcp import McpError, call_http
from eivon.adapters.network import OutboundDenied


class Chunked(httpx.AsyncByteStream):
    def __init__(self, chunks):
        self.chunks = chunks

    async def __aiter__(self):
        for chunk in self.chunks:
            yield chunk


@pytest.mark.asyncio
@pytest.mark.parametrize("sse", [False, True])
async def test_handshake_session_headers_and_matching_response(sse):
    calls = []

    def handler(request):
        if request.method == "DELETE":
            calls.append("delete")
            assert request.headers["mcp-session-id"] == "session-one"
            return httpx.Response(405)
        body = json.loads(request.content)
        calls.append(body["method"])
        if body["method"] == "initialize":
            assert "mcp-session-id" not in request.headers
            return httpx.Response(
                200,
                headers={"Mcp-Session-Id": "session-one"},
                json={
                    "jsonrpc": "2.0",
                    "id": body["id"],
                    "result": {
                        "protocolVersion": "2025-06-18",
                        "capabilities": {"tools": {}},
                        "serverInfo": {"name": "test", "version": "1"},
                    },
                },
            )
        assert request.headers["MCP-Protocol-Version"] == "2025-06-18"
        assert request.headers["Mcp-Session-Id"] == "session-one"
        if body["method"] == "notifications/initialized":
            return httpx.Response(202)
        assert body["params"] == {"name": "lookup", "arguments": {"id": "x"}}
        payload = {
            "jsonrpc": "2.0",
            "id": body["id"],
            "result": {"structuredContent": {"ok": True}},
        }
        if not sse:
            return httpx.Response(200, json=payload)
        notification = b'data: {"jsonrpc":"2.0","method":"notifications/progress"}\r\n\r\n'
        message = (
            "data: " + json.dumps(payload, indent=2).replace("\n", "\ndata: ") + "\r\n\r\n"
        ).encode()
        # Split arbitrarily across fields and data. The parser returns as soon as the
        # matching event arrives, before a connection closes or later events appear.
        return httpx.Response(
            200,
            headers={"content-type": "text/event-stream"},
            stream=Chunked([notification[:9], notification[9:], message[:17], message[17:]]),
        )

    result = await call_http(
        "https://mcp.example.test/mcp",
        "lookup",
        {"id": "x"},
        ("mcp.example.test",),
        transport=httpx.MockTransport(handler),
    )
    assert result == {"ok": True}
    assert calls == ["initialize", "notifications/initialized", "tools/call", "delete"]


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", ["id", "version", "size", "redirect", "remote_error"])
async def test_rejects_invalid_or_unbounded_responses_without_retry(failure):
    calls = []

    def handler(request):
        calls.append(request)
        body = json.loads(request.content)
        if failure == "size":
            return httpx.Response(
                200,
                headers={"content-type": "application/json"},
                stream=Chunked([b" " * 200, b" " * 200]),
            )
        if failure == "redirect":
            return httpx.Response(302, headers={"Location": "https://private.test"})
        payload = {
            "jsonrpc": "2.0",
            "id": "other" if failure == "id" else body["id"],
            "result": {"protocolVersion": "unsupported", "capabilities": {"tools": {}}},
        }
        if failure == "remote_error":
            payload = {"jsonrpc": "2.0", "id": body["id"], "error": {"message": "secret-token"}}
        return httpx.Response(200, json=payload)

    with pytest.raises(McpError) as error:
        await call_http(
            "https://mcp.example.test/mcp",
            "lookup",
            {},
            ("mcp.example.test",),
            transport=httpx.MockTransport(handler),
            max_response_bytes=256,
        )
    assert "secret-token" not in str(error.value)
    assert len(calls) == 1


@pytest.mark.asyncio
async def test_unconfigured_destination_never_sends_request():
    def handler(request):
        pytest.fail("No network request is authorized")

    with pytest.raises(OutboundDenied):
        await call_http(
            "https://denied.test/mcp", "lookup", {}, (), transport=httpx.MockTransport(handler)
        )
