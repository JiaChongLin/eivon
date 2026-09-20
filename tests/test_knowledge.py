def test_workspace_scoped_knowledge_ingestion_and_search(client, owner):
    collection = client.post(
        "/api/v1/knowledge/collections", json={"name": "Manuals", "description": "Test"}
    )
    assert collection.status_code == 201
    collection_id = collection.json()["id"]
    document = client.post(
        "/api/v1/knowledge/documents",
        json={
            "collection_id": collection_id,
            "title": "Guide",
            "content": "A blue engine requires a safe restart procedure.",
            "source_uri": "manual://guide",
        },
    )
    assert document.status_code == 201
    result = client.post(
        "/api/v1/knowledge/search",
        json={"collection_ids": [collection_id], "query": "blue engine restart"},
    )
    assert result.status_code == 200
    assert result.json()["items"][0]["title"] == "Guide"
    assert result.json()["items"][0]["source_uri"] == "manual://guide"


def test_semantic_hybrid_search_and_connection_binding(client, owner):
    from .conftest import create_resource, publish

    connection = create_resource(
        client,
        "connection",
        "knowledge-api",
        {"adapter": "http", "base_url": "https://knowledge.example.test"},
    )
    publish(client, connection)
    connection = client.get(f"/api/v1/resources/{connection['id']}").json()
    assert client.get("/api/v1/knowledge/connections").json()["items"][0]["active_version"] == 1
    tested = client.post(f"/api/v1/knowledge/connections/{connection['id']}/test")
    assert tested.status_code == 200 and tested.json()["status"] == "configured"
    collection = client.post(
        "/api/v1/knowledge/collections",
        json={"name": "Semantic", "connection_id": connection["id"]},
    )
    assert collection.status_code == 201, collection.text
    collection_id = collection.json()["id"]
    assert collection.json()["connection_version"] == 1
    assert (
        client.post(
            "/api/v1/knowledge/documents",
            json={
                "collection_id": collection_id,
                "title": "Reset guide",
                "content": "A vehicle can restart after a safe engine reset.",
                "source_uri": "manual://reset",
            },
        ).status_code
        == 201
    )
    semantic = client.post(
        "/api/v1/knowledge/search",
        json={"collection_ids": [collection_id], "query": "engine restart", "mode": "semantic"},
    )
    assert semantic.status_code == 200 and semantic.json()["items"][0]["semantic_score"] > 0
    hybrid = client.post(
        "/api/v1/knowledge/search",
        json={"collection_ids": [collection_id], "query": "engine restart", "mode": "hybrid"},
    ).json()["items"][0]
    assert {"score", "lexical_score", "semantic_score", "collection_id"}.issubset(hybrid)
    assert (
        client.post(
            "/api/v1/knowledge/search",
            json={"collection_ids": [collection_id], "query": "engine", "mode": "unknown"},
        ).status_code
        == 422
    )


def test_knowledge_connection_and_embedding_scope_are_workspace_bound(client, owner):
    from .conftest import create_resource, publish

    connection = create_resource(
        client,
        "connection",
        "private-api",
        {"adapter": "http", "base_url": "https://private.example.test"},
    )
    publish(client, connection)
    workspace = client.post("/api/v1/workspaces", json={"name": "Knowledge other"}).json()
    client.headers["x-eivon-workspace"] = workspace["id"]
    response = client.post(f"/api/v1/knowledge/connections/{connection['id']}/test")
    assert response.status_code == 404, response.text
    assert (
        client.post(
            "/api/v1/knowledge/collections",
            json={"name": "Wrong", "connection_id": connection["id"]},
        ).status_code
        == 404
    )
    assert (
        client.post(
            "/api/v1/knowledge/search", json={"collection_ids": ["not-in-space"], "query": "engine"}
        ).status_code
        == 403
    )
