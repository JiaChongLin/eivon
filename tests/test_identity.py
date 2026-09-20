from fastapi.testclient import TestClient
from sqlalchemy import select

from eivon.server.db import Credential, Token, User


def test_setup_is_single_use_and_passwords_are_hashed(client, owner, app):
    response = client.post(
        "/api/v1/setup",
        json={
            "setup_token": "test-setup-token",
            "email": "other@example.test",
            "password": "long-test-password",
            "name": "Other",
        },
    )
    assert response.status_code == 409
    with app.state.database.transaction() as db:
        user = db.scalar(select(User))
        assert user.password_hash.startswith("scrypt$")
        assert "long-test-password" not in user.password_hash
        token = db.scalar(select(Token))
        assert token.digest != client.cookies.get("eivon_session")


def test_unauthenticated_and_csrf_requests_fail(client, owner):
    token = client.headers.pop("x-csrf-token")
    assert client.post("/api/v1/workspaces", json={"name": "No CSRF"}).status_code == 403
    client.headers["x-csrf-token"] = token
    assert client.post("/api/v1/auth/logout").status_code == 204
    assert client.get("/api/v1/resources").status_code == 401


def test_workspace_and_api_key_scope_are_enforced(client, owner):
    key = client.post("/api/v1/api-keys", json={"name": "Readonly", "permissions": ["read"]}).json()
    second = client.post("/api/v1/workspaces", json={"name": "Second"}).json()
    headers = {
        "Authorization": "Bearer " + key["secret"],
        "x-eivon-workspace": owner["workspace_id"],
    }
    assert client.get("/api/v1/resources", headers=headers).status_code == 200
    assert (
        client.post("/api/v1/workspaces", headers=headers, json={"name": "Denied"}).status_code
        == 403
    )
    headers["x-eivon-workspace"] = second["id"]
    assert client.get("/api/v1/resources", headers=headers).status_code == 403
    assert client.delete("/api/v1/api-keys/" + key["id"]).status_code == 204
    headers["x-eivon-workspace"] = owner["workspace_id"]
    assert client.get("/api/v1/resources", headers=headers).status_code == 401


def test_credentials_are_encrypted_and_never_returned(client, owner, app):
    response = client.post(
        "/api/v1/credentials", json={"name": "Provider", "value": "super-secret-provider-value"}
    )
    assert response.status_code == 201
    credential_id = response.json()["id"]
    assert "super-secret" not in response.text
    assert "super-secret" not in client.get("/api/v1/credentials").text
    with app.state.database.transaction() as db:
        credential = db.get(Credential, credential_id)
        assert "super-secret" not in credential.encrypted_value
    assert (
        app.state.security.credential_value(owner["workspace_id"], credential_id)
        == "super-secret-provider-value"
    )


def test_member_permissions_and_revocation(app, client, owner):
    added = client.post(
        "/api/v1/members",
        json={
            "name": "Viewer",
            "email": "viewer@example.test",
            "password": "viewer-test-password",
            "role": "viewer",
        },
    )
    assert added.status_code == 201
    with TestClient(app) as viewer:
        response = viewer.post(
            "/api/v1/auth/login",
            json={"email": "viewer@example.test", "password": "viewer-test-password"},
        )
        assert response.status_code == 200
        viewer.headers["x-csrf-token"] = response.json()["csrf_token"]
        assert viewer.get("/api/v1/resources").status_code == 200
        assert (
            viewer.post(
                "/api/v1/resources",
                json={
                    "kind": "prompt",
                    "name": "Forbidden",
                    "slug": "nope",
                    "spec": {"template": "no"},
                },
            ).status_code
            == 403
        )
        assert client.delete("/api/v1/members/" + added.json()["user_id"]).status_code == 204
        assert viewer.get("/api/v1/resources").status_code == 403


def test_login_rate_limit_is_persistent(client, owner):
    for _ in range(10):
        assert (
            client.post(
                "/api/v1/auth/login", json={"email": "owner@example.test", "password": "incorrect"}
            ).status_code
            == 401
        )
    assert (
        client.post(
            "/api/v1/auth/login", json={"email": "owner@example.test", "password": "incorrect"}
        ).status_code
        == 429
    )


def test_validation_errors_do_not_echo_password(client):
    response = client.post(
        "/api/v1/setup",
        json={
            "setup_token": "test-setup-token",
            "email": "bad",
            "password": "secret-value",
            "name": "Owner",
        },
    )
    assert response.status_code == 422
    assert "secret-value" not in response.text
