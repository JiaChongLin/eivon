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


def test_workspace_management_rotation_and_audit_are_scoped(client, owner, app):
    first = owner["workspace_id"]
    credential = client.post(
        "/api/v1/credentials", json={"name": "Provider", "value": "initial-private-value"}
    ).json()
    second = client.post("/api/v1/workspaces", json={"name": "Second"}).json()["id"]
    key = client.post(
        "/api/v1/api-keys", json={"name": "Scoped reader", "permissions": ["read"]}
    ).json()
    key_headers = {"Authorization": "Bearer " + key["secret"], "x-eivon-workspace": first}
    identity = client.get("/api/v1/auth/me", headers=key_headers).json()
    assert [item["id"] for item in identity["workspaces"]] == [first]
    assert client.get("/api/v1/audit-events", headers=key_headers).status_code == 403
    assert (
        client.put(
            f"/api/v1/credentials/{credential['id']}",
            headers={"x-eivon-workspace": second},
            json={"name": "Denied", "value": "cross-workspace-value"},
        ).status_code
        == 404
    )
    rotated = client.put(
        f"/api/v1/credentials/{credential['id']}",
        json={"name": "Rotated", "value": "replacement-private-value"},
    )
    assert rotated.status_code == 200
    assert rotated.json()["id"] == credential["id"]
    assert "private-value" not in rotated.text
    assert (
        app.state.security.credential_value(first, credential["id"]) == "replacement-private-value"
    )
    assert (
        client.patch(
            f"/api/v1/workspaces/{first}",
            headers={"x-eivon-workspace": second},
            json={"name": "Wrong space"},
        ).status_code
        == 404
    )
    assert (
        client.patch(f"/api/v1/workspaces/{first}", json={"name": "Renamed workspace"}).status_code
        == 200
    )
    assert any(
        item["name"] == "Renamed workspace"
        for item in client.get("/api/v1/auth/me").json()["workspaces"]
    )
    audit = client.get("/api/v1/audit-events").json()
    actions = {item["action"] for item in audit["items"]}
    assert {
        "credential.create",
        "credential.rotate",
        "workspace.rename",
        "api_key.create",
    } <= actions
    assert "private-value" not in str(audit) and key["secret"] not in str(audit)
    assert (
        client.get("/api/v1/audit-events", headers={"x-eivon-workspace": second}).json()["total"]
        == 0
    )
    page = client.get("/api/v1/audit-events?limit=1").json()
    next_page = client.get("/api/v1/audit-events?limit=1&offset=1").json()
    assert page["total"] == audit["total"]
    assert page["items"][0]["id"] != next_page["items"][0]["id"]


def test_role_changes_restrict_existing_keys_and_revoked_member_can_logout(client, owner, app):
    member = client.post(
        "/api/v1/members",
        json={
            "name": "Administrator",
            "email": "admin@example.test",
            "password": "long-admin-password",
            "role": "admin",
        },
    ).json()
    with TestClient(app) as admin:
        login = admin.post(
            "/api/v1/auth/login",
            json={"email": "admin@example.test", "password": "long-admin-password"},
        ).json()
        admin.headers["x-csrf-token"] = login["csrf_token"]
        key = admin.post(
            "/api/v1/api-keys",
            json={"name": "Authoring", "permissions": ["read", "write", "admin"]},
        ).json()
        assert (
            admin.post(
                "/api/v1/members",
                json={
                    "name": "Escalation",
                    "email": "escalate@example.test",
                    "password": "long-test-password",
                    "role": "admin",
                },
            ).status_code
            == 403
        )
        assert (
            client.patch(
                f"/api/v1/members/{owner['user']['id']}", json={"role": "viewer"}
            ).status_code
            == 409
        )
        assert (
            client.patch(
                f"/api/v1/members/{member['user_id']}", json={"role": "viewer"}
            ).status_code
            == 200
        )
        assert admin.get("/api/v1/members").status_code == 403
        headers = {"Authorization": "Bearer " + key["secret"]}
        assert admin.get("/api/v1/resources", headers=headers).status_code == 200
        assert (
            admin.post(
                "/api/v1/resources",
                headers=headers,
                json={
                    "kind": "prompt",
                    "name": "Denied",
                    "slug": "denied",
                    "spec": {"template": "denied"},
                },
            ).status_code
            == 403
        )
        assert client.delete(f"/api/v1/members/{member['user_id']}").status_code == 204
        assert admin.get("/api/v1/resources", headers=headers).status_code == 401
        assert admin.get("/api/v1/auth/me").status_code == 403
        # CSRF discovery remains authenticated by the session, independently of membership.
        csrf = admin.get("/api/v1/auth/session")
        assert csrf.status_code == 200
        assert (
            admin.post("/api/v1/auth/logout", headers={"x-csrf-token": "wrong"}).status_code == 403
        )
        admin.headers["x-csrf-token"] = csrf.json()["csrf_token"]
        assert admin.post("/api/v1/auth/logout").status_code == 204
        assert admin.get("/api/v1/auth/session").status_code == 401


def test_member_email_validation_and_explicit_key_revocation(client, owner):
    assert (
        client.post(
            "/api/v1/members",
            json={"name": "Invalid", "email": "not-an-email", "password": "long-test-password"},
        ).status_code
        == 422
    )
    key = client.post(
        "/api/v1/api-keys",
        json={"name": "Expire or revoke", "permissions": ["read"], "expires_in_days": 1},
    ).json()
    assert key["expires_at"] > key["created_at"]
    assert "secret" not in client.get("/api/v1/api-keys").json()["items"][0]
    assert client.delete(f"/api/v1/api-keys/{key['id']}").status_code == 204
    assert (
        client.get(
            "/api/v1/resources", headers={"Authorization": "Bearer " + key["secret"]}
        ).status_code
        == 401
    )
