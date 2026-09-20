"""Exercise Agent lifecycle through persisted Runs and real tool adapters."""

import asyncio

from fastapi.testclient import TestClient

from eivon.core.contracts import ModelResponse, ToolCall
from eivon.server.tool_runtime import ToolRuntime, tool_name

from .conftest import create_resource, publish


def test_tool_batch_survives_two_approval_pauses_and_delivers_private_file(
    client, owner, app, monkeypatch
):
    model_ref = publish(client, create_resource(client, "model", "script-model", {"model": "test"}))
    tool_refs = [
        publish(client, create_resource(client, "tool", slug, spec))
        for slug, spec in [
            ("read-echo", {"description": "Read", "effect": "read"}),
            ("write-echo", {"description": "Write", "effect": "write"}),
            (
                "export-file",
                {"description": "Export", "effect": "write", "entrypoint": "export_text"},
            ),
        ]
    ]
    agent = create_resource(
        client, "agent", "batch-agent", {"model_ref": model_ref, "tool_refs": tool_refs}
    )
    publish(client, agent)
    seen = []
    executed = []
    original = ToolRuntime._execute

    async def spy(runtime, spec, arguments):
        executed.append(arguments)
        return await original(runtime, spec, arguments)

    monkeypatch.setattr(ToolRuntime, "_execute", spy)

    class Model:
        def __init__(self, *args):
            pass

        async def complete(self, messages, definitions, emit):
            seen.append(messages)
            replies = [message for message in messages if message.role == "tool"]
            if not replies:
                return ModelResponse(
                    tool_calls=[
                        ToolCall(
                            id="read-before", name=tool_name(tool_refs[0]), arguments={"order": 1}
                        ),
                        ToolCall(id="write", name=tool_name(tool_refs[1]), arguments={"order": 2}),
                        ToolCall(
                            id="export",
                            name=tool_name(tool_refs[2]),
                            arguments={"name": "报告.md", "content": "A portable report"},
                        ),
                        ToolCall(
                            id="read-after", name=tool_name(tool_refs[0]), arguments={"order": 4}
                        ),
                    ]
                )
            assert [message.tool_call_id for message in replies] == [
                "read-before",
                "write",
                "export",
                "read-after",
            ]
            return ModelResponse(content="Report ready")

    monkeypatch.setattr("eivon.server.worker.CompatibleModel", Model)
    run_id = client.post(
        "/api/v1/runs", json={"resource_id": agent["id"], "message": "Write a report"}
    ).json()["id"]
    for approval in range(2):
        assert asyncio.run(app.state.worker.once())
        waiting = client.get(f"/api/v1/runs/{run_id}").json()
        assert waiting["status"] == "waiting_approval", waiting
        assert len(executed) == approval + 1
        result = client.post(
            f"/api/v1/runs/{run_id}/resume",
            json={"response": {"approved": True}, "expected_sequence": waiting["event_sequence"]},
        )
        assert result.status_code == 200, result.text
        # Duplicate submit must not approve a different call or advance execution.
        assert (
            client.post(
                f"/api/v1/runs/{run_id}/resume",
                json={
                    "response": {"approved": True},
                    "expected_sequence": waiting["event_sequence"],
                },
            ).status_code
            == 409
        )
    assert asyncio.run(app.state.worker.once())
    completed = client.get(f"/api/v1/runs/{run_id}").json()
    assert completed["status"] == "completed", completed
    assert completed["output"]["text"] == "Report ready"
    assert len(executed) == 4
    assert len(seen) == 2
    files = client.get(f"/api/v1/runs/{run_id}/artifacts").json()["items"]
    assert len(files) == 1
    artifact_id = files[0]["id"]
    download = client.get(f"/api/v1/artifacts/{artifact_id}/download")
    assert download.status_code == 200
    assert download.text == "A portable report"
    assert "%E6%8A%A5%E5%91%8A.md" in download.headers["content-disposition"]
    member = client.post(
        "/api/v1/members",
        json={
            "name": "Other",
            "email": "other@example.test",
            "password": "another-test-password",
            "role": "operator",
        },
    )
    assert member.status_code == 201
    with TestClient(app) as other:
        assert (
            other.post(
                "/api/v1/auth/login",
                json={"email": "other@example.test", "password": "another-test-password"},
            ).status_code
            == 200
        )
        assert other.get(f"/api/v1/runs/{run_id}/artifacts").status_code == 404
        assert other.get(f"/api/v1/artifacts/{artifact_id}/download").status_code == 404
    second_workspace = client.post("/api/v1/workspaces", json={"name": "Other workspace"}).json()[
        "id"
    ]
    assert (
        client.get(
            f"/api/v1/runs/{run_id}/artifacts", headers={"x-eivon-workspace": second_workspace}
        ).status_code
        == 404
    )


def test_bundle_prompts_and_preloaded_skills_are_visible_to_model(client, owner, app, monkeypatch):
    model_ref = publish(
        client, create_resource(client, "model", "context-model", {"model": "test"})
    )
    prompt = publish(
        client,
        create_resource(
            client,
            "prompt",
            "bundle-prompt",
            {"template": "You help {{team}}", "variables": {"team": "research"}},
        ),
    )
    skill = publish(
        client,
        create_resource(
            client,
            "skill",
            "preloaded-skill",
            {
                "description": "Review evidence",
                "body": "Distinguish observation from inference.",
                "preload": True,
            },
        ),
    )
    lazy = publish(
        client,
        create_resource(
            client,
            "skill",
            "lazy-skill",
            {"description": "Read references", "body": "LAZY BODY", "preload": False},
        ),
    )
    bundle = publish(
        client,
        create_resource(
            client,
            "bundle",
            "research-bundle",
            {"prompt_refs": [prompt], "skill_refs": [skill, lazy]},
        ),
    )
    agent = create_resource(
        client,
        "agent",
        "research-agent",
        {"model_ref": model_ref, "prompt_refs": [prompt], "bundle_refs": [bundle]},
    )
    publish(client, agent)

    class Model:
        def __init__(self, *args):
            pass

        async def complete(self, messages, tools, emit):
            system = messages[0].content
            assert system.count("You help research") == 1
            assert "Distinguish observation from inference." in system
            assert "LAZY BODY" not in system
            assert lazy["id"] in system
            assert "eivon_skill_read" in system
            assert "UNTRUSTED PAYLOAD" not in system
            assert "UNTRUSTED PAYLOAD" in messages[1].content
            assert messages[1].role == "user"
            assert messages[-1].content == "Hello"
            return ModelResponse(content="Ready")

    monkeypatch.setattr("eivon.server.worker.CompatibleModel", Model)
    run_id = client.post(
        "/api/v1/runs",
        json={
            "resource_id": agent["id"],
            "message": "Hello",
            "context": {"note": "UNTRUSTED PAYLOAD"},
        },
    ).json()["id"]
    assert asyncio.run(app.state.worker.once())
    run = client.get(f"/api/v1/runs/{run_id}").json()
    assert run["status"] == "completed", run
