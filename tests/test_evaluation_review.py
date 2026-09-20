from eivon.server.db import Job, Run

from .conftest import create_resource, publish


def evaluation_fixture(client):
    prompt = create_resource(client, "prompt", "eval-prompt", {"template": "Original instructions"})
    prompt_ref = publish(client, prompt)
    model = publish(
        client,
        create_resource(client, "model", "eval-model", {"provider": "demo", "model": "demo"}),
    )
    agent = create_resource(
        client, "agent", "eval-agent", {"model_ref": model, "prompt_refs": [prompt_ref]}
    )
    publish(client, agent)
    current = client.get(f"/api/v1/resources/{agent['id']}").json()
    changed = client.put(
        f"/api/v1/resources/{agent['id']}",
        json={
            "revision": current["revision"],
            "name": current["name"],
            "spec": {**current["draft"], "greeting": "New greeting"},
        },
    ).json()
    publish(client, changed)
    evaluation = client.post(
        "/api/v1/evaluations",
        json={
            "name": "Regression",
            "cases": [
                {"input": "one", "expected": "correct", "match": "exact"},
                {"input": "two", "expected": "correct", "match": "contains"},
            ],
        },
    ).json()
    return prompt, agent, evaluation


def scored_job(client, app, agent, evaluation, version, outputs):
    response = client.post(
        f"/api/v1/evaluations/{evaluation['id']}/run",
        json={"resource_id": agent["id"], "version": version},
    )
    assert response.status_code == 202, response.text
    job = response.json()
    with app.state.database.transaction() as db:
        for run_id, output in zip(job["input"]["run_ids"], outputs, strict=True):
            run = db.get(Run, run_id)
            run.status = "completed"
            run.output = {"text": output}
    app.state.evaluations.reconcile()
    return client.get(f"/api/v1/evaluation-jobs/{job['id']}").json()


def test_compare_batches_and_append_human_scores(client, app, owner):
    prompt, agent, evaluation = evaluation_fixture(client)
    baseline = scored_job(client, app, agent, evaluation, 1, ["wrong", "correct"])
    candidate = scored_job(client, app, agent, evaluation, 2, ["correct", "wrong"])
    url = f"/api/v1/evaluation-comparison?baseline={baseline['id']}&candidate={candidate['id']}"
    comparison = client.get(url).json()
    assert comparison["improved"] == comparison["regressed"] == 1
    assert comparison["score_delta"] == 0
    assert [row["change"] for row in comparison["cases"]] == ["improved", "regressed"]
    review_url = (
        f"/api/v1/evaluation-jobs/{candidate['id']}/results/{candidate['results'][1]['id']}/reviews"
    )
    for score in [0.2, 0.7]:
        assert (
            client.post(review_url, json={"score": score, "note": "Human rubric"}).status_code
            == 201
        )
    refreshed = client.get(url).json()["cases"][1]["candidate"]
    assert refreshed["score"] == 0
    assert [r["score"] for r in refreshed["reviews"]] == [0.2, 0.7]
    assert client.post(review_url, json={"score": 2, "note": "bad"}).status_code == 422
    jobs = client.get(f"/api/v1/evaluations/{evaluation['id']}/jobs?limit=1").json()
    assert jobs["total"] == 2 and jobs["items"][0]["resource_version"] == 2
    another = client.post(
        "/api/v1/evaluations",
        json={"name": "Different", "cases": [{"input": "hello", "match": "nonempty"}]},
    ).json()
    # Many unrelated jobs must not hide this set's history.
    with app.state.database.transaction() as db:
        for _ in range(101):
            db.add(
                Job(
                    workspace_id=owner["workspace_id"],
                    user_id=owner["user"]["id"],
                    kind="evaluation",
                    status="completed",
                    input={"evaluation_set_id": another["id"]},
                )
            )
    assert len(client.get(f"/api/v1/evaluations/{evaluation['id']}").json()["jobs"]) == 2
    pending = client.post(
        f"/api/v1/evaluations/{evaluation['id']}/run", json={"resource_id": agent["id"]}
    ).json()
    assert (
        client.get(
            f"/api/v1/evaluation-comparison?baseline={baseline['id']}&candidate={pending['id']}"
        ).status_code
        == 409
    )
    # Same shapes from another test set still do not constitute comparable evidence.
    other_set = {**evaluation, "id": another["id"]}
    other = scored_job(client, app, agent, other_set, 1, ["correct"])
    assert (
        client.get(
            f"/api/v1/evaluation-comparison?baseline={baseline['id']}&candidate={other['id']}"
        ).status_code
        == 422
    )


def test_reviewed_improvement_is_atomic_and_never_publishes(client, app, owner):
    prompt, agent, evaluation = evaluation_fixture(client)
    job = scored_job(client, app, agent, evaluation, 1, ["wrong", "wrong"])
    root = f"/api/v1/evaluation-jobs/{job['id']}"
    reflection = client.get(root + "/reflection").json()
    assert len(reflection["failures"]) == 2
    assert reflection["targets"][0]["id"] == prompt["id"]
    current = client.get(f"/api/v1/resources/{prompt['id']}").json()
    payload = {
        "resource_id": prompt["id"],
        "revision": current["revision"],
        "text": "Improved instructions",
        "rationale": "Address failure in case 1",
    }
    proposal_response = client.post(root + "/proposals", json=payload)
    assert proposal_response.status_code == 201, proposal_response.text
    proposal = proposal_response.json()
    before = client.get(f"/api/v1/resources/{prompt['id']}").json()
    assert before == current
    decision = root + f"/proposals/{proposal['id']}/review"
    accepted = client.post(decision, json={"decision": "accepted", "note": "Reviewed evidence"})
    assert accepted.status_code == 200, accepted.text
    assert accepted.json()["applied_revision"] == current["revision"] + 1
    after = client.get(f"/api/v1/resources/{prompt['id']}").json()
    assert after["draft"]["template"] == "Improved instructions"
    assert after["active_version"] == after["latest_version"] == 1
    frozen = client.get(f"/api/v1/resources/{prompt['id']}/versions/1").json()
    assert frozen["spec"]["template"] == "Original instructions"
    assert client.post(decision, json={"decision": "accepted", "note": "Again"}).status_code == 409
    # A newer author edit causes the entire decision transaction to roll back.
    payload.update(revision=after["revision"], text="Another improvement")
    stale = client.post(root + "/proposals", json=payload).json()
    client.put(
        f"/api/v1/resources/{prompt['id']}",
        json={
            "revision": after["revision"],
            "name": after["name"],
            "spec": {"template": "Concurrent edit"},
        },
    )
    stale_url = root + f"/proposals/{stale['id']}/review"
    assert client.post(stale_url, json={"decision": "accepted", "note": "Stale"}).status_code == 409
    reflected = client.get(root + "/reflection").json()
    assert next(p for p in reflected["proposals"] if p["id"] == stale["id"])["status"] == "pending"
    assert (
        client.post(stale_url, json={"decision": "rejected", "note": "Superseded"}).status_code
        == 200
    )
    assert (
        client.get(f"/api/v1/resources/{prompt['id']}").json()["draft"]["template"]
        == "Concurrent edit"
    )
    assert (
        client.post(root + "/proposals", json={**payload, "resource_id": agent["id"]}).status_code
        == 422
    )


def test_evaluation_review_permissions_and_workspace_isolation(client, app, owner):
    prompt, agent, evaluation = evaluation_fixture(client)
    job = scored_job(client, app, agent, evaluation, 1, ["wrong", "wrong"])
    root = f"/api/v1/evaluation-jobs/{job['id']}"
    target = client.get(root + "/reflection").json()["targets"][0]
    proposal = client.post(
        root + "/proposals",
        json={
            "resource_id": prompt["id"],
            "revision": target["revision"],
            "text": "Candidate",
            "rationale": "Testing isolation",
        },
    ).json()
    key = client.post("/api/v1/api-keys", json={"name": "Reader", "permissions": ["read"]}).json()[
        "secret"
    ]
    headers = {"authorization": f"Bearer {key}"}
    assert client.get(root, headers=headers).status_code == 200
    assert (
        client.post(
            root + f"/results/{job['results'][0]['id']}/reviews",
            headers=headers,
            json={"score": 1, "note": "No write"},
        ).status_code
        == 403
    )
    assert (
        client.post(
            root + f"/proposals/{proposal['id']}/review",
            headers=headers,
            json={"decision": "accepted", "note": "No admin"},
        ).status_code
        == 403
    )
    admin_key = client.post(
        "/api/v1/api-keys", json={"name": "Review metadata only", "permissions": ["read", "admin"]}
    ).json()["secret"]
    assert (
        client.post(
            root + f"/proposals/{proposal['id']}/review",
            headers={"authorization": f"Bearer {admin_key}"},
            json={"decision": "accepted", "note": "No draft write permission"},
        ).status_code
        == 403
    )
    assert client.get(root + "/reflection").json()["proposals"][0]["status"] == "pending"
    client.post(
        "/api/v1/members",
        json={
            "name": "Other",
            "email": "other@example.test",
            "password": "other-test-password",
            "role": "editor",
        },
    )
    login = client.post(
        "/api/v1/auth/login",
        json={"email": "other@example.test", "password": "other-test-password"},
    ).json()
    client.headers["x-csrf-token"] = login["csrf_token"]
    assert client.get(root).status_code == 404
    assert client.get(root + "/reflection").status_code == 404
    assert client.get(f"/api/v1/evaluations/{evaluation['id']}/jobs").json()["total"] == 0
    client.post(
        "/api/v1/auth/login", json={"email": "owner@example.test", "password": "long-test-password"}
    )
    client.headers["x-csrf-token"] = owner["csrf_token"]
    # Use the restored session's CSRF for mutations.
    client.headers["x-csrf-token"] = client.get("/api/v1/auth/me").json()["csrf_token"]
    other = client.post("/api/v1/workspaces", json={"name": "Other workspace"}).json()
    client.headers["x-eivon-workspace"] = other["id"]
    assert client.get(root).status_code == 404
    assert client.get(root + "/reflection").status_code == 404
    assert (
        client.post(
            root + f"/proposals/{proposal['id']}/review",
            json={"decision": "accepted", "note": "Wrong scope"},
        ).status_code
        == 404
    )


def test_evaluation_schema_upgrade_preserves_history(client, app, owner):
    from sqlalchemy import inspect

    from eivon.server.db import EvaluationReview, ImprovementProposal, Meta
    from eivon.server.migrations import upgrade

    prompt, agent, evaluation = evaluation_fixture(client)
    job = scored_job(client, app, agent, evaluation, 1, ["wrong", "correct"])
    EvaluationReview.__table__.drop(app.state.database.engine)
    ImprovementProposal.__table__.drop(app.state.database.engine)
    with app.state.database.transaction() as db:
        db.get(Meta, "schema_version").value = "3"
    assert upgrade(app.state.database) == 4
    assert upgrade(app.state.database) == 4
    tables = inspect(app.state.database.engine).get_table_names()
    assert "evaluation_reviews" in tables and "improvement_proposals" in tables
    detail = client.get(f"/api/v1/evaluation-jobs/{job['id']}").json()
    assert detail["output"]["score"] == 0.5
    assert len(detail["results"]) == 2
    assert detail["results"][0]["reviews"] == []


def test_future_schema_is_rejected_before_additive_changes(app):
    import pytest
    from sqlalchemy import inspect

    from eivon.server.db import EvaluationReview, Meta
    from eivon.server.migrations import upgrade

    EvaluationReview.__table__.drop(app.state.database.engine)
    with app.state.database.transaction() as db:
        db.get(Meta, "schema_version").value = "999"
    with pytest.raises(RuntimeError, match="Unsupported database schema"):
        upgrade(app.state.database)
    assert "evaluation_reviews" not in inspect(app.state.database.engine).get_table_names()
