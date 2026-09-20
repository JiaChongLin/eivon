from .conftest import create_resource, publish


def test_published_snapshot_survives_draft_edits(client, owner):
    prompt = create_resource(client, "prompt", "system", {"template": "Original instructions"})
    ref = publish(client, prompt)
    model = publish(
        client,
        create_resource(client, "model", "local-demo", {"provider": "demo", "model": "offline"}),
    )
    agent = create_resource(
        client, "agent", "assistant", {"model_ref": model, "prompt_refs": [ref]}
    )
    release = publish(client, agent)
    current = client.get(f"/api/v1/resources/{prompt['id']}").json()
    changed = client.put(
        f"/api/v1/resources/{prompt['id']}",
        json={
            "revision": current["revision"],
            "name": "System",
            "spec": {"template": "Changed instructions"},
        },
    )
    assert changed.status_code == 200
    publish(client, changed.json())
    snapshot = client.get(f"/api/v1/resources/{agent['id']}/versions/{release['version']}").json()[
        "snapshot"
    ]
    assert snapshot["resources"][f"{prompt['id']}@1"]["spec"]["template"] == "Original instructions"


def test_stale_writes_and_publish_are_rejected(client, owner):
    item = create_resource(client, "prompt", "system", {"template": "One"})
    publish(client, item)
    assert (
        client.put(
            f"/api/v1/resources/{item['id']}",
            json={"revision": 1, "name": "Stale", "spec": {"template": "Two"}},
        ).status_code
        == 409
    )
    assert (
        client.post(f"/api/v1/resources/{item['id']}/publish", json={"revision": 1}).status_code
        == 409
    )


def test_cross_workspace_reference_is_rejected(client, owner):
    tool = publish(
        client, create_resource(client, "tool", "echo", {"description": "Echo arguments"})
    )
    second = client.post("/api/v1/workspaces", json={"name": "Other"}).json()
    client.headers["x-eivon-workspace"] = second["id"]
    assert client.get(f"/api/v1/resources/{tool['id']}").status_code == 404
    bundle = create_resource(client, "bundle", "cross-workspace", {"tool_refs": [tool]})
    assert (
        client.post(f"/api/v1/resources/{bundle['id']}/publish", json={"revision": 1}).status_code
        == 404
    )


def test_conflicting_bundle_versions_fail_publication(client, owner):
    tool = create_resource(client, "tool", "echo", {"description": "First"})
    v1 = publish(client, tool)
    current = client.get(f"/api/v1/resources/{tool['id']}").json()
    v2 = publish(client, current)
    one = publish(client, create_resource(client, "bundle", "one", {"tool_refs": [v1]}))
    two = publish(client, create_resource(client, "bundle", "two", {"tool_refs": [v2]}))
    model = publish(
        client, create_resource(client, "model", "demo", {"provider": "demo", "model": "demo"})
    )
    agent = create_resource(
        client, "agent", "conflict", {"model_ref": model, "bundle_refs": [one, two]}
    )
    response = client.post(f"/api/v1/resources/{agent['id']}/publish", json={"revision": 1})
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "version_conflict"


def test_remote_schema_references_and_invalid_workflows_are_rejected(client, owner):
    response = client.post(
        "/api/v1/resources",
        json={
            "kind": "tool",
            "name": "Invalid",
            "slug": "invalid",
            "spec": {"description": "remote", "input_schema": {"$ref": "http://localhost/private"}},
        },
    )
    assert response.status_code == 400
    response = client.post(
        "/api/v1/resources",
        json={
            "kind": "workflow",
            "name": "Invalid",
            "slug": "invalid",
            "spec": {
                "steps": [
                    {
                        "type": "condition",
                        "id": "check",
                        "value_path": "input.x",
                        "skip_step_ids": ["missing"],
                    }
                ]
            },
        },
    )
    assert response.status_code == 422


def test_archive_preserves_version_and_prevents_new_publish(client, owner):
    resource = create_resource(client, "prompt", "system", {"template": "Instructions"})
    publish(client, resource)
    response = client.post(f"/api/v1/resources/{resource['id']}/archive", json={"revision": 2})
    assert response.status_code == 200
    assert client.get("/api/v1/resources").json()["total"] == 0
    assert client.get(f"/api/v1/resources/{resource['id']}/versions/1").status_code == 200
    assert (
        client.post(f"/api/v1/resources/{resource['id']}/publish", json={"revision": 3}).status_code
        == 409
    )


def test_search_literal_wildcard(client, owner):
    create_resource(client, "prompt", "system", {"template": "Instructions"})
    assert client.get("/api/v1/resources", params={"search": "%"}).json()["total"] == 0


def test_archived_listing_is_filtered_paginated_and_workspace_scoped(client, owner):
    ids = []
    for slug in ["archive-one", "archive-two", "archive-three"]:
        item = create_resource(client, "prompt", slug, {"template": slug})
        ids.append(item["id"])
        assert (
            client.post(f"/api/v1/resources/{item['id']}/archive", json={"revision": 1}).status_code
            == 200
        )
    create_resource(client, "tool", "visible-tool", {"description": "Visible"})
    page = client.get(
        "/api/v1/resources",
        params={"archived": True, "kind": "prompt", "search": "Archive", "limit": 2},
    ).json()
    assert page["total"] == 3 and len(page["items"]) == 2
    second = client.get(
        "/api/v1/resources",
        params={"archived": True, "kind": "prompt", "search": "Archive", "limit": 2, "offset": 2},
    ).json()
    assert len(second["items"]) == 1
    assert {item["id"] for item in page["items"] + second["items"]} == set(ids)
    assert client.get("/api/v1/resources").json()["total"] == 1
    other = client.post("/api/v1/workspaces", json={"name": "Other"}).json()["id"]
    assert (
        client.get("/api/v1/resources?archived=true", headers={"x-eivon-workspace": other}).json()[
            "total"
        ]
        == 0
    )
    assert (
        client.post(
            f"/api/v1/resources/{ids[0]}/archive", json={"revision": 2, "archived": False}
        ).status_code
        == 200
    )
    assert client.get("/api/v1/resources?archived=true").json()["total"] == 2
    assert client.get("/api/v1/resources").json()["total"] == 2


def test_release_rollback_affects_only_future_runs_and_preserves_draft(client, owner, app):
    import asyncio

    tool = publish(
        client, create_resource(client, "tool", "rollback-echo", {"description": "Echo"})
    )
    spec = {
        "steps": [{"type": "tool", "id": "echo", "tool_ref": tool}],
        "output_template": "first release",
    }
    workflow = create_resource(client, "workflow", "rollback-flow", spec)
    publish(client, workflow)
    updated = client.put(
        f"/api/v1/resources/{workflow['id']}",
        json={
            "revision": 2,
            "name": "Rollback flow",
            "spec": {**spec, "output_template": "second release"},
        },
    ).json()
    publish(client, updated)
    before = client.get(f"/api/v1/resources/{workflow['id']}/versions/2").json()
    old_run = client.post("/api/v1/runs", json={"resource_id": workflow["id"]}).json()
    activated = client.post(
        f"/api/v1/resources/{workflow['id']}/activate", json={"revision": 4, "version": 1}
    )
    assert activated.status_code == 200, activated.text
    assert activated.json()["draft"]["output_template"] == "second release"
    assert activated.json()["latest_version"] == 2
    assert activated.json()["active_version"] == 1
    stale = client.post(
        f"/api/v1/resources/{workflow['id']}/activate", json={"revision": 4, "version": 2}
    )
    assert stale.status_code == 409
    new_run = client.post("/api/v1/runs", json={"resource_id": workflow["id"]}).json()
    assert old_run["resource_version"] == 2 and new_run["resource_version"] == 1
    assert asyncio.run(app.state.worker.once())
    assert asyncio.run(app.state.worker.once())
    assert client.get(f"/api/v1/runs/{old_run['id']}").json()["output"]["text"] == "second release"
    assert client.get(f"/api/v1/runs/{new_run['id']}").json()["output"]["text"] == "first release"
    after = client.get(f"/api/v1/resources/{workflow['id']}/versions/2").json()
    assert before == after


def test_validation_checks_revision_and_archive_restore_checks_permissions(client, owner, app):
    from fastapi.testclient import TestClient

    item = create_resource(client, "prompt", "validation-draft", {"template": "Original"})
    assert (
        client.post(f"/api/v1/resources/{item['id']}/validate", json={"revision": 1}).status_code
        == 200
    )
    publish(client, item)
    assert (
        client.post(f"/api/v1/resources/{item['id']}/validate", json={"revision": 1}).status_code
        == 409
    )
    assert client.post(f"/api/v1/resources/{item['id']}/validate").status_code == 200
    client.post(
        "/api/v1/members",
        json={
            "name": "Reader",
            "email": "reader@example.test",
            "password": "long-reader-password",
            "role": "viewer",
        },
    )
    client.post(f"/api/v1/resources/{item['id']}/archive", json={"revision": 2})
    with TestClient(app) as reader:
        login = reader.post(
            "/api/v1/auth/login",
            json={"email": "reader@example.test", "password": "long-reader-password"},
        ).json()
        reader.headers["x-csrf-token"] = login["csrf_token"]
        assert reader.get("/api/v1/resources?archived=true").json()["total"] == 1
        assert reader.get(f"/api/v1/resources/{item['id']}/versions/1").status_code == 200
        assert (
            reader.post(
                f"/api/v1/resources/{item['id']}/archive", json={"revision": 3, "archived": False}
            ).status_code
            == 403
        )
        assert (
            reader.post(
                f"/api/v1/resources/{item['id']}/activate", json={"revision": 3, "version": 1}
            ).status_code
            == 403
        )
