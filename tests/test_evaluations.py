import asyncio
from pathlib import Path
from tempfile import TemporaryDirectory
from time import sleep

from fastapi.testclient import TestClient

from eivon.server.app import create_app
from eivon.server.settings import Settings


def test_evaluation_job_scores_published_agent():
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
                return {"id": item["id"], "version": response.json()["version"]}

            model = publish(create("model", "demo-model", {"provider": "demo", "model": "demo"}))
            agent = create("agent", "demo-agent", {"model_ref": model})
            publish(agent)
            evaluation = client.post(
                "/api/v1/evaluations",
                json={
                    "name": "Smoke set",
                    "cases": [{"input": "hello", "expected": "hello", "match": "contains"}],
                },
            )
            assert evaluation.status_code == 201, evaluation.text
            started = client.post(
                f"/api/v1/evaluations/{evaluation.json()['id']}/run",
                json={"resource_id": agent["id"]},
            )
            assert started.status_code == 202, started.text
            for _ in range(100):
                job = client.get(f"/api/v1/evaluation-jobs/{started.json()['id']}").json()
                if job["status"] in {"completed", "timed_out", "failed"}:
                    break
                sleep(0.05)
            assert job["status"] == "completed", job
            assert job["output"]["score"] == 1.0
            detail = client.get(f"/api/v1/evaluations/{evaluation.json()['id']}").json()
            assert detail["results"][0]["status"] == "passed"


def test_evaluation_reconciles_from_database_without_api_task():
    with TemporaryDirectory() as directory:
        app = create_app(
            Settings(data_dir=Path(directory), setup_token="setup", inline_worker=False)
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
                return {"id": item["id"], "version": response.json()["version"]}

            model = publish(create("model", "restart-model", {"provider": "demo", "model": "demo"}))
            agent = create("agent", "restart-agent", {"model_ref": model})
            publish(agent)
            evaluation = client.post(
                "/api/v1/evaluations",
                json={"name": "restart", "cases": [{"input": "recover", "match": "nonempty"}]},
            ).json()
            started = client.post(
                f"/api/v1/evaluations/{evaluation['id']}/run", json={"resource_id": agent["id"]}
            )
            assert started.status_code == 202
            for _ in range(3):
                asyncio.run(app.state.worker.once())
            job = client.get(f"/api/v1/evaluation-jobs/{started.json()['id']}").json()
            assert job["status"] == "completed", job
            assert job["output"]["score"] == 1.0
