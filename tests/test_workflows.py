"""Workflow execution checks using real releases, leases and persisted resumes."""

import asyncio

import pytest

from eivon.core.contracts import ModelResponse
from eivon.core.workflows import WorkflowBindingError, bind_arguments, json_equal, resolve_path
from eivon.server.worker import RunWorker

from .conftest import create_resource, publish


def start_workflow(client, spec, **payload):
    workflow = create_resource(client, "workflow", "tested-workflow", spec)
    publish(client, workflow)
    response = client.post("/api/v1/runs", json={"resource_id": workflow["id"], **payload})
    assert response.status_code == 202, response.text
    return response.json()["id"]


def tick(app, client, run_id):
    assert asyncio.run(app.state.worker.once())
    return client.get(f"/api/v1/runs/{run_id}").json()


def test_noncontiguous_skips_survive_empty_input_resume(client, owner, app):
    tool = publish(client, create_resource(client, "tool", "echo", {"description": "Echo"}))
    run_id = start_workflow(
        client,
        {
            "input_schema": {"type": "object", "required": ["skip", "value"]},
            "steps": [
                {
                    "id": "branch",
                    "type": "condition",
                    "value_path": "input.skip",
                    "equals": True,
                    "skip_step_ids": ["unwanted_before", "unwanted_after"],
                },
                {"id": "unwanted_before", "type": "tool", "tool_ref": tool},
                {"id": "answer", "type": "input", "question": "Continue?"},
                {"id": "unwanted_after", "type": "tool", "tool_ref": tool},
                {
                    "id": "kept",
                    "type": "tool",
                    "tool_ref": tool,
                    "arguments": {"value": "{{input.value}}", "answer": "{{steps.answer}}"},
                },
            ],
            "output_template": "Value={{steps.kept.data.value}}; answer={{steps.answer}}",
        },
        input={"skip": True, "value": [3, False]},
    )
    waiting = tick(app, client, run_id)
    assert waiting["status"] == "waiting_input", waiting
    response = client.post(
        f"/api/v1/runs/{run_id}/resume",
        json={
            "response": {},
            "expected_sequence": waiting["event_sequence"],
        },
    )
    assert response.status_code == 200, response.text
    # A fresh worker must read all branch decisions and the empty response from the DB.
    app.state.worker = RunWorker(
        app.state.database,
        app.state.runs,
        app.state.settings,
        app.state.security,
        app.state.artifacts,
        app.state.extensions,
        worker_id="new-worker",
    )
    completed = tick(app, client, run_id)
    assert completed["status"] == "completed", completed
    assert completed["output"]["text"] == "Value=[3, false]; answer={}"
    assert set(completed["output"]["steps"]) == {"branch", "answer", "kept"}
    assert completed["output"]["steps"]["kept"]["data"]["value"] == [3, False]
    events = client.get(f"/api/v1/runs/{run_id}/events").json()["items"]
    assert [
        event["data"]["step_id"] for event in events if event["type"] == "workflow.step.skipped"
    ] == ["unwanted_before", "unwanted_after"]


def test_prompt_steps_use_their_own_models_and_render_results(client, owner, app, monkeypatch):
    observed = []

    class FakeModel:
        def __init__(self, spec, credential, allowed_hosts):
            self.name = spec.model

        async def complete(self, messages, tools, emit):
            assert tools == []
            observed.append((self.name, messages[0].content))
            return ModelResponse(content=f"{self.name}:{messages[0].content}")

    monkeypatch.setattr("eivon.server.worker.CompatibleModel", FakeModel)
    models = [
        publish(client, create_resource(client, "model", name, {"model": name}))
        for name in ["first", "second"]
    ]
    run_id = start_workflow(
        client,
        {
            "steps": [
                {
                    "id": "one",
                    "type": "prompt",
                    "model_ref": models[0],
                    "template": "{{input.message}}",
                },
                {
                    "id": "two",
                    "type": "prompt",
                    "model_ref": models[1],
                    "template": "{{steps.one.text}}",
                },
            ],
            "output_template": "{{steps.two.text}}",
        },
        message="hello",
    )
    run = tick(app, client, run_id)
    assert run["status"] == "completed", run
    assert observed == [("first", "hello"), ("second", "first:hello")]
    assert run["output"]["text"] == "second:first:hello"


def test_workflow_input_and_resume_schemas_are_enforced(client, owner, app):
    spec = {
        "input_schema": {
            "type": "object",
            "required": ["count"],
            "properties": {"count": {"type": "integer"}},
        },
        "steps": [
            {
                "id": "answer",
                "type": "input",
                "question": "Amount?",
                "input_schema": {
                    "type": "object",
                    "required": ["amount"],
                    "properties": {"amount": {"type": "number"}},
                },
            }
        ],
    }
    workflow = create_resource(client, "workflow", "validated-flow", spec)
    publish(client, workflow)
    invalid = client.post(
        "/api/v1/runs", json={"resource_id": workflow["id"], "input": {"count": "wrong"}}
    )
    assert invalid.status_code == 422
    run_id = client.post(
        "/api/v1/runs", json={"resource_id": workflow["id"], "input": {"count": 2}}
    ).json()["id"]
    waiting = tick(app, client, run_id)
    invalid_resume = client.post(
        f"/api/v1/runs/{run_id}/resume",
        json={"response": {"amount": "wrong"}, "expected_sequence": waiting["event_sequence"]},
    )
    assert invalid_resume.status_code == 422
    assert client.get(f"/api/v1/runs/{run_id}").json()["status"] == "waiting_input"


def test_missing_binding_fails_before_invoking_tool(client, owner, app):
    tool = publish(client, create_resource(client, "tool", "guarded-echo", {"description": "Echo"}))
    run_id = start_workflow(
        client,
        {
            "steps": [
                {
                    "id": "echo",
                    "type": "tool",
                    "tool_ref": tool,
                    "arguments": {"value": "{{steps.absent.data}}"},
                }
            ]
        },
    )
    run = tick(app, client, run_id)
    assert run["status"] == "failed", run
    assert run["error"] == "Workflow value is unavailable: steps.absent.data"
    assert run["output"]["steps"] == {}


def test_cancel_interrupts_an_inflight_prompt(client, owner, app, monkeypatch):
    started, interrupted = asyncio.Event(), asyncio.Event()

    class SlowModel:
        def __init__(self, *args):
            pass

        async def complete(self, *args):
            started.set()
            try:
                await asyncio.Event().wait()
            finally:
                interrupted.set()

    monkeypatch.setattr("eivon.server.worker.CompatibleModel", SlowModel)
    model = publish(client, create_resource(client, "model", "slow-model", {"model": "slow"}))
    run_id = start_workflow(
        client,
        {"steps": [{"id": "slow", "type": "prompt", "model_ref": model, "template": "Wait"}]},
    )

    async def execute():
        task = asyncio.create_task(app.state.worker.once())
        await asyncio.wait_for(started.wait(), 2)
        assert client.post(f"/api/v1/runs/{run_id}/cancel").status_code == 200
        await asyncio.wait_for(task, 2)
        assert interrupted.is_set()

    asyncio.run(execute())
    assert client.get(f"/api/v1/runs/{run_id}").json()["status"] == "cancelled"


def test_data_bindings_preserve_types_without_evaluating_code():
    scope = {"input": {"items": [False, {"amount": 0}], "text": "{{steps.secret}}"}, "steps": {}}
    assert bind_arguments(
        {"flag": "{{input.items.0}}", "amount": "{{input.items.1.amount}}"}, scope
    ) == {"flag": False, "amount": 0}
    assert bind_arguments("{{input.text}}", scope) == "{{steps.secret}}"
    assert bind_arguments("literal {{__import__('os')}}", scope) == "literal {{__import__('os')}}"
    with pytest.raises(WorkflowBindingError):
        resolve_path("input.__class__", scope)
    assert not json_equal(True, 1)
    assert not json_equal({"nested": [False]}, {"nested": [0]})
    assert json_equal(1, 1.0)
