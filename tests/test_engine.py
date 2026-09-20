import asyncio

import pytest

from eivon.core.contracts import ExecutionPolicy, ModelMessage, ModelResponse, ToolCall, ToolResult
from eivon.core.engine import (
    AgentEngine,
    BudgetExceeded,
    EngineState,
    ExecutionCancelled,
    PauseExecution,
    cancellable,
)


class ScriptedModel:
    def __init__(self, responses):
        self.responses = iter(responses)
        self.calls = []

    async def complete(self, messages, tools, emit):
        self.calls.append(list(messages))
        return next(self.responses)


class ApprovingTool:
    def __init__(self):
        self.approved = False
        self.executions = 0

    async def invoke(self, call):
        if not self.approved:
            raise PauseExecution("waiting_approval", {"call_id": call.id})
        self.executions += 1
        return ToolResult(success=True, data={"answer": 42})


async def noop(*args):
    pass


async def never_cancelled():
    return False


async def test_approval_resume_does_not_repeat_model_or_completed_tool():
    model = ScriptedModel(
        [
            ModelResponse(tool_calls=[ToolCall(id="call-1", name="lookup")]),
            ModelResponse(content="42"),
        ]
    )
    tool = ApprovingTool()
    engine = AgentEngine(model, tool, [], ExecutionPolicy())
    state = EngineState(messages=[ModelMessage(role="user", content="Get the answer")])
    with pytest.raises(PauseExecution):
        await engine.run(state, noop, noop, never_cancelled)
    assert len(model.calls) == 1
    assert tool.executions == 0
    tool.approved = True
    restored = EngineState.model_validate_json(state.model_dump_json())
    result = await engine.run(restored, noop, noop, never_cancelled)
    assert tool.executions == 1
    assert len(model.calls) == 2
    assert result.output == "42"
    assert model.calls[1][-1].tool_call_id == "call-1"


async def test_iteration_budget_is_enforced():
    model = ScriptedModel([ModelResponse(tool_calls=[ToolCall(id="call-1", name="lookup")])])
    tool = ApprovingTool()
    tool.approved = True
    engine = AgentEngine(model, tool, [], ExecutionPolicy(max_iterations=1))
    with pytest.raises(BudgetExceeded):
        await engine.run(EngineState(), noop, noop, never_cancelled)
    assert tool.executions == 1


async def test_cancellation_cancels_underlying_task():
    stopped = asyncio.Event()

    async def operation():
        try:
            await asyncio.Event().wait()
        finally:
            stopped.set()

    calls = 0

    async def cancelled():
        nonlocal calls
        calls += 1
        return calls > 1

    with pytest.raises(ExecutionCancelled):
        await cancellable(operation(), cancelled, 5)
    assert stopped.is_set()
