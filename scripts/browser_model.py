"""Deterministic HTTP model fixture used only by the disposable browser server."""

import asyncio
import json

import httpx

from eivon.adapters.models import CompatibleModel


async def respond(request: httpx.Request) -> httpx.Response:
    body = json.loads(request.content)
    messages = body["messages"]
    user_messages = [item for item in messages if item["role"] == "user"]
    prompt = user_messages[-1]["content"]
    if prompt == "Hold for cancellation":
        await asyncio.Event().wait()
    last_user = max(i for i, message in enumerate(messages) if message["role"] == "user")
    results = [message for message in messages[last_user + 1 :] if message["role"] == "tool"]
    if len(user_messages) == 1 and not results and body.get("tools"):
        delta = {
            "tool_calls": [
                {
                    "index": 0,
                    "id": "browser-export",
                    "type": "function",
                    "function": {
                        "name": body["tools"][0]["function"]["name"],
                        "arguments": json.dumps(
                            {"name": "报告.md", "content": "Browser acceptance report"}
                        ),
                    },
                }
            ]
        }
        finish = "tool_calls"
    else:
        delta = {"content": f"[Test fixture] Turn {len(user_messages)}: {prompt}"}
        finish = "stop"
    event = {"choices": [{"index": 0, "delta": delta, "finish_reason": finish}]}
    return httpx.Response(
        200,
        text="data: " + json.dumps(event) + "\n\ndata: [DONE]\n\n",
        headers={"content-type": "text/event-stream"},
    )


class BrowserModel(CompatibleModel):
    def __init__(self, spec, credential, allowed_hosts):
        super().__init__(spec, credential, allowed_hosts, transport=httpx.MockTransport(respond))
