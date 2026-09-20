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
