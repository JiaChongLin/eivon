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


def test_semantic_hybrid_search_and_connection_binding(client, app, owner):
    from .conftest import create_resource, publish

    object.__setattr__(app.state.settings, "allowed_hosts", ("knowledge.example.test",))

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


def test_provider_embedding_resource_is_bound_and_used_for_index_and_query(client, app, owner, monkeypatch):
    from eivon.adapters import embeddings as embeddings_module

    from .conftest import create_resource, publish

    object.__setattr__(app.state.settings, "allowed_hosts", ("embed.example.test",))
    embedding_resource = create_resource(
        client,
        "embedding",
        "remote-embedding",
        {
            "provider": "openai_compatible",
            "model": "embed-test",
            "base_url": "https://embed.example.test/v1",
            "dimensions": 96,
        },
    )
    publish(client, embedding_resource)

    class Response:
        content = b'{"data": []}'

        def raise_for_status(self):
            pass

        def json(self):
            return {"data": [{"index": index, "embedding": [0.25] * 96} for index in range(self.count)]}

    class Client:
        def __init__(self, **kwargs):
            self.kwargs = kwargs

        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

        def post(self, url, headers, json):
            assert url == "https://embed.example.test/v1/embeddings"
            assert json["model"] == "embed-test"
            response = Response()
            response.count = len(json["input"])
            return response

    monkeypatch.setattr(embeddings_module.httpx, "Client", Client)
    collection = client.post(
        "/api/v1/knowledge/collections",
        json={"name": "Remote vectors", "embedding_resource_id": embedding_resource["id"]},
    )
    assert collection.status_code == 201, collection.text
    assert collection.json()["embedding_resource_version"] == 1
    document = client.post(
        "/api/v1/knowledge/documents",
        json={"collection_id": collection.json()["id"], "title": "Vector guide", "content": "Remote vector content"},
    )
    assert document.status_code == 201, document.text
    result = client.post(
        "/api/v1/knowledge/search",
        json={"collection_ids": [collection.json()["id"]], "query": "anything", "mode": "semantic"},
    )
    assert result.status_code == 200, result.text
    assert result.json()["items"][0]["semantic_score"] == 1.0


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


def test_connection_sync_imports_and_deduplicates_documents(client, app, owner, monkeypatch):
    from eivon.server import knowledge as knowledge_module

    from .conftest import create_resource, publish

    object.__setattr__(app.state.settings, "allowed_hosts", ("knowledge.example.test",))
    connection = create_resource(
        client,
        "connection",
        "sync-api",
        {"adapter": "http", "base_url": "https://knowledge.example.test/documents"},
    )
    publish(client, connection)
    collection = client.post(
        "/api/v1/knowledge/collections", json={"name": "Synced", "connection_id": connection["id"]}
    ).json()

    class Response:
        content = b'{"documents": [{"title": "Remote guide", "content": "A remote engine guide.", "source_uri": "remote://guide"}]}'

        def raise_for_status(self):
            pass

        def json(self):
            return {
                "documents": [
                    {
                        "title": "Remote guide",
                        "content": "A remote engine guide.",
                        "source_uri": "remote://guide",
                    }
                ]
            }

    class Client:
        def __init__(self, **kwargs):
            self.kwargs = kwargs

        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

        def get(self, url, headers):
            assert url.startswith("https://knowledge.example.test")
            return Response()

    monkeypatch.setattr(knowledge_module.httpx, "Client", Client)
    first = client.post(f"/api/v1/knowledge/collections/{collection['id']}/sync")
    second = client.post(f"/api/v1/knowledge/collections/{collection['id']}/sync")
    assert first.status_code == second.status_code == 200
    assert first.json()["imported"] == 1 and second.json()["skipped"] == 1
    hits = client.post(
        "/api/v1/knowledge/search",
        json={"collection_ids": [collection["id"]], "query": "remote guide"},
    ).json()["items"]
    assert len(hits) == 1 and hits[0]["source_uri"] == "remote://guide"
