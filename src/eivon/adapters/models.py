"""Streaming chat-completions adapter and an explicitly labelled offline demo provider."""

from __future__ import annotations

import json
from typing import Any

import httpx

from eivon.core.contracts import ModelMessage, ModelResponse, ModelSpec, ToolCall
from eivon.core.engine import Emit

from .network import check_destination


class ModelUnavailable(RuntimeError):
    pass


def provider_messages(messages: list[ModelMessage]) -> list[dict]:
    result = []
    for message in messages:
        item: dict[str, Any] = {"role": message.role, "content": message.content}
        if message.tool_call_id:
            item["tool_call_id"] = message.tool_call_id
        if message.tool_calls:
            item["tool_calls"] = [
                {
                    "id": c.id,
                    "type": "function",
                    "function": {"name": c.name, "arguments": json.dumps(c.arguments)},
                }
                for c in message.tool_calls
            ]
        result.append(item)
    return result


class CompatibleModel:
    def __init__(
        self,
        spec: ModelSpec,
        credential: str | None,
        allowed_hosts: tuple[str, ...],
        transport=None,
    ):
        self.spec, self.credential, self.allowed_hosts, self.transport = (
            spec,
            credential,
            allowed_hosts,
            transport,
        )

    async def complete(
        self, messages: list[ModelMessage], tools: list[dict], emit: Emit
    ) -> ModelResponse:
        url = check_destination(
            self.spec.base_url.rstrip("/") + "/chat/completions", self.allowed_hosts
        )
        headers = {"Content-Type": "application/json"}
        if self.credential:
            headers["Authorization"] = f"Bearer {self.credential}"
        payload: dict = {
            "model": self.spec.model,
            "messages": provider_messages(messages),
            "temperature": self.spec.temperature,
            "max_tokens": self.spec.max_output_tokens,
            "stream": True,
            "stream_options": {"include_usage": True},
        }
        if tools:
            payload["tools"] = tools
        text_parts, calls, usage = [], {}, {}
        finished = False
        total_bytes = 0
        try:
            async with httpx.AsyncClient(
                timeout=self.spec.timeout_seconds,
                follow_redirects=False,
                trust_env=False,
                transport=self.transport,
            ) as client:
                async with client.stream("POST", url, headers=headers, json=payload) as response:
                    if response.status_code != 200:
                        raise ModelUnavailable(
                            f"Model endpoint returned HTTP {response.status_code}"
                        )
                    async for line in response.aiter_lines():
                        total_bytes += len(line.encode())
                        if total_bytes > 4_000_000:
                            raise ModelUnavailable("Model response exceeds 4 MB")
                        if not line.startswith("data:"):
                            continue
                        data = line[5:].strip()
                        if data == "[DONE]":
                            finished = True
                            break
                        if not data:
                            continue
                        event = json.loads(data)
                        if event.get("usage"):
                            usage = {
                                k: int(v)
                                for k, v in event["usage"].items()
                                if isinstance(v, int) and v >= 0
                            }
                        for choice in event.get("choices", []):
                            if choice.get("index", 0) != 0:
                                continue
                            if choice.get("finish_reason"):
                                finished = True
                                if choice["finish_reason"] in {"length", "content_filter"}:
                                    raise ModelUnavailable(
                                        "Model response ended before completion: "
                                        + choice["finish_reason"]
                                    )
                            delta = choice.get("delta", {})
                            if delta.get("content"):
                                content = str(delta["content"])
                                text_parts.append(content)
                                await emit("message.delta", {"text": content})
                            for fragment in delta.get("tool_calls", []):
                                index = fragment.get("index", 0)
                                if not isinstance(index, int) or not 0 <= index < 100:
                                    raise ModelUnavailable("Model returned an invalid tool index")
                                call = calls.setdefault(
                                    index, {"id": "", "name": "", "arguments": ""}
                                )
                                if fragment.get("id"):
                                    call["id"] = fragment["id"]
                                call["name"] += fragment.get("function", {}).get("name", "")
                                call["arguments"] += fragment.get("function", {}).get(
                                    "arguments", ""
                                )
            if not finished:
                raise ModelUnavailable("Model stream disconnected before completion")
            tool_calls = []
            for index in sorted(calls):
                call = calls[index]
                arguments = json.loads(call["arguments"] or "{}")
                if not isinstance(arguments, dict) or not call["id"] or not call["name"]:
                    raise ModelUnavailable("Model returned an invalid tool call")
                tool_calls.append(ToolCall(id=call["id"], name=call["name"], arguments=arguments))
            if len({c.id for c in tool_calls}) != len(tool_calls):
                raise ModelUnavailable("Model returned duplicate tool call IDs")
            return ModelResponse(content="".join(text_parts), tool_calls=tool_calls, usage=usage)
        except (httpx.HTTPError, json.JSONDecodeError, TypeError, KeyError) as exc:
            raise ModelUnavailable(
                "Model connection failed or returned an invalid response"
            ) from exc


class DemoModel:
    """A deterministic connectivity/demo fixture, never presented as an actual LLM."""

    async def complete(
        self, messages: list[ModelMessage], tools: list[dict], emit: Emit
    ) -> ModelResponse:
        user_text = next((m.content or "" for m in reversed(messages) if m.role == "user"), "")
        text = "[Offline demo — no language model connected]\n\n" + user_text
        await emit("message.delta", {"text": text})
        return ModelResponse(content=text)
