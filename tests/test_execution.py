from pathlib import Path
from tempfile import TemporaryDirectory
from time import sleep

from fastapi.testclient import TestClient

from eivon.server.app import create_app
from eivon.server.settings import Settings


def test_published_agent_runs_through_inline_worker():
    with TemporaryDirectory() as directory:
        app = create_app(
            Settings(data_dir=Path(directory), setup_token="setup", inline_worker=True)
        )
        with TestClient(app) as client:
            setup = client.post(
                "/api/v1/setup",
                json={
                    "setup_token": "setup",
                    "email": "owner@example.test",
                    "password": "long-test-password",
                    "name": "Owner",
                },
            )
            assert setup.status_code == 201
            client.headers["x-csrf-token"] = setup.json()["csrf_token"]

            def create(kind, slug, spec):
                response = client.post(
                    "/api/v1/resources",
                    json={"kind": kind, "name": slug, "slug": slug, "spec": spec},
                )
                assert response.status_code == 201, response.text
                return response.json()

            def publish(item):
                response = client.post(
                    f"/api/v1/resources/{item['id']}/publish", json={"revision": item["revision"]}
                )
                assert response.status_code == 201, response.text
                data = response.json()
                return {"id": data["id"], "version": data["version"]}

            model = publish(create("model", "offline", {"provider": "demo", "model": "offline"}))
            prompt = publish(create("prompt", "instructions", {"template": "Be concise."}))
            agent = create("agent", "assistant", {"model_ref": model, "prompt_refs": [prompt]})
            publish(agent)
            created = client.post(
                "/api/v1/runs", json={"resource_id": agent["id"], "message": "Hello"}
            )
            assert created.status_code == 202, created.text
            run_id = created.json()["id"]
            for _ in range(50):
                run = client.get(f"/api/v1/runs/{run_id}").json()
                if run["status"] in {"completed", "failed", "cancelled"}:
                    break
                sleep(0.05)
            assert run["status"] == "completed", run
            assert "Hello" in run["output"]["text"]
            events = client.get(f"/api/v1/runs/{run_id}/events").json()["items"]
            assert [event["sequence"] for event in events] == list(range(1, len(events) + 1))
            assert events[-1]["type"] == "run.completed"


def test_workflow_approval_waits_and_resumes_once():
    with TemporaryDirectory() as directory:
        app = create_app(
            Settings(data_dir=Path(directory), setup_token="setup", inline_worker=True)
        )
        with TestClient(app) as client:
            setup = client.post(
                "/api/v1/setup",
                json={
                    "setup_token": "setup",
                    "email": "owner@example.test",
                    "password": "long-test-password",
                    "name": "Owner",
                },
            )
            client.headers["x-csrf-token"] = setup.json()["csrf_token"]

            def create(kind, slug, spec):
                response = client.post(
                    "/api/v1/resources",
                    json={"kind": kind, "name": slug, "slug": slug, "spec": spec},
                )
                assert response.status_code == 201, response.text
                return response.json()

            def publish(item):
                response = client.post(
                    f"/api/v1/resources/{item['id']}/publish", json={"revision": item["revision"]}
                )
                assert response.status_code == 201, response.text
                data = response.json()
                return {"id": data["id"], "version": data["version"]}

            tool = publish(
                create(
                    "tool",
                    "write-echo",
                    {
                        "description": "Write",
                        "entrypoint": "echo",
                        "effect": "write",
                        "input_schema": {"type": "object"},
                    },
                )
            )
            workflow = create(
                "workflow",
                "approval-flow",
                {
                    "steps": [
                        {
                            "type": "tool",
                            "id": "write",
                            "tool_ref": tool,
                            "arguments": {"value": "approved"},
                        }
                    ]
                },
            )
            publish(workflow)
            run = client.post(
                "/api/v1/runs", json={"resource_id": workflow["id"], "message": "Run"}
            ).json()
            for _ in range(50):
                current = client.get(f"/api/v1/runs/{run['id']}").json()
                if current["status"] in {"waiting_approval", "failed", "completed"}:
                    break
                sleep(0.05)
            assert current["status"] == "waiting_approval", current
            resumed = client.post(
                f"/api/v1/runs/{run['id']}/resume",
                json={
                    "response": {"approved": True},
                    "expected_sequence": current["event_sequence"],
                },
            )
            assert resumed.status_code == 200, resumed.text
            for _ in range(50):
                current = client.get(f"/api/v1/runs/{run['id']}").json()
                if current["status"] in {"completed", "failed", "cancelled"}:
                    break
                sleep(0.05)
            assert current["status"] == "completed", current
            assert current["output"]["steps"]["write"]["success"] is True
