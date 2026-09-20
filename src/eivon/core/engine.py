"""Resumable agent loop independent of HTTP, persistence, and business domains."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from typing import Any, Protocol

from pydantic import Field

from .contracts import Contract, ExecutionPolicy, ModelMessage, ModelResponse, ToolCall, ToolResult

Emit = Callable[[str, dict[str, Any]], Awaitable[None]]


class EngineState(Contract):
    messages: list[ModelMessage] = Field(default_factory=list)
    pending_calls: list[ToolCall] = Field(default_factory=list)
    pending_index: int = 0
    iterations: int = 0
    tool_calls: int = 0
    usage: dict[str, int] = Field(default_factory=dict)
    output: str = ""


class Model(Protocol):
    async def complete(
        self, messages: list[ModelMessage], tools: list[dict], emit: Emit
    ) -> ModelResponse: ...


class ToolRunner(Protocol):
    async def invoke(self, call: ToolCall) -> ToolResult: ...


class PauseExecution(Exception):
    def __init__(self, status: str, payload: dict):
        super().__init__(status)
        self.status, self.payload = status, payload


class ExecutionCancelled(Exception):
    pass


class BudgetExceeded(Exception):
    pass


class AgentEngine:
    def __init__(
        self, model: Model, tools: ToolRunner, definitions: list[dict], policy: ExecutionPolicy
    ):
        self.model, self.tools, self.definitions, self.policy = model, tools, definitions, policy

    async def run(
        self,
        state: EngineState,
        emit: Emit,
        save: Callable[[EngineState], Awaitable[None]],
        cancelled: Callable[[], Awaitable[bool]],
    ) -> EngineState:
        async def check():
            if await cancelled():
                raise ExecutionCancelled()

        while state.iterations < self.policy.max_iterations or state.pending_calls:
            await check()
            while state.pending_index < len(state.pending_calls):
                await check()
                if state.tool_calls >= self.policy.max_tool_calls:
                    raise BudgetExceeded("Tool call budget exhausted")
                call = state.pending_calls[state.pending_index]
                await save(state)
                await emit(
                    "tool.started",
                    {"call_id": call.id, "name": call.name, "arguments": call.arguments},
                )
                result = await self.tools.invoke(call)
                state.tool_calls += 1
                state.messages.append(
                    ModelMessage(
                        role="tool", tool_call_id=call.id, content=result.model_dump_json()
                    )
                )
                state.pending_index += 1
                await save(state)
                await emit(
                    "tool.completed", {"call_id": call.id, "name": call.name, **result.model_dump()}
                )
            state.pending_calls = []
            state.pending_index = 0
            if state.iterations >= self.policy.max_iterations:
                raise BudgetExceeded("Model iteration budget exhausted")
            total_chars = sum(len(m.model_dump_json()) for m in state.messages)
            if total_chars > self.policy.max_input_chars:
                raise BudgetExceeded(
                    "Conversation input budget exhausted; start a new session or shorten inputs"
                )
            await check()
            await emit("model.started", {"iteration": state.iterations + 1})
            response = await self.model.complete(state.messages, self.definitions, emit)
            state.iterations += 1
            for key, amount in response.usage.items():
                state.usage[key] = state.usage.get(key, 0) + amount
            if len(response.tool_calls) > self.policy.max_tool_calls - state.tool_calls:
                raise BudgetExceeded("Model requested more tools than the remaining budget")
            state.messages.append(
                ModelMessage(
                    role="assistant",
                    content=response.content or None,
                    tool_calls=response.tool_calls,
                )
            )
            state.pending_calls = response.tool_calls
            state.output = response.content
            await save(state)
            await emit(
                "model.completed",
                {
                    "iteration": state.iterations,
                    "usage": response.usage,
                    "tool_calls": len(response.tool_calls),
                },
            )
            if not response.tool_calls:
                return state
        raise BudgetExceeded("Model iteration budget exhausted")


async def cancellable(awaitable, cancelled: Callable[[], Awaitable[bool]], timeout: float):
    """Propagate cancellation to network/tool tasks without declaring success early."""
    task = asyncio.create_task(awaitable)
    loop = asyncio.get_running_loop()
    deadline = loop.time() + timeout
    try:
        while not task.done():
            if await cancelled():
                raise ExecutionCancelled()
            remaining = deadline - loop.time()
            if remaining <= 0:
                raise TimeoutError("Execution deadline exceeded")
            await asyncio.wait({task}, timeout=min(0.25, remaining))
        return await task
    finally:
        if not task.done():
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass
