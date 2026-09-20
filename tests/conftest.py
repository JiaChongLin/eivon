from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from eivon.server.app import create_app
from eivon.server.settings import Settings


@pytest.fixture
def app(tmp_path):
    return create_app(
        Settings(
            data_dir=tmp_path, setup_token="test-setup-token", inline_worker=False, testing=True
        )
    )


@pytest.fixture
def client(app):
    with TestClient(app) as client:
        yield client


@pytest.fixture
def owner(client):
    response = client.post(
        "/api/v1/setup",
        json={
            "setup_token": "test-setup-token",
            "email": "owner@example.test",
            "password": "long-test-password",
            "name": "Owner",
            "workspace_name": "Research",
        },
    )
    assert response.status_code == 201, response.text
    data = response.json()
    client.headers["x-csrf-token"] = data["csrf_token"]
    client.headers["x-eivon-workspace"] = data["workspace_id"]
    return data


def create_resource(client, kind, slug, spec):
    response = client.post(
        "/api/v1/resources", json={"kind": kind, "slug": slug, "name": slug.title(), "spec": spec}
    )
    assert response.status_code == 201, response.text
    return response.json()


def publish(client, resource):
    response = client.post(
        f"/api/v1/resources/{resource['id']}/publish", json={"revision": resource["revision"]}
    )
    assert response.status_code == 201, response.text
    return {"id": resource["id"], "version": response.json()["version"]}
