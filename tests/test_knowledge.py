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
