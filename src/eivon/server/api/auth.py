"""Instance setup, sign-in, workspace members and access credentials."""

from __future__ import annotations

import hmac

from fastapi import APIRouter, Request, Response
from pydantic import Field, field_validator
from sqlalchemy import delete, select

from eivon.core.contracts import Contract

from ..db import Credential, Member, Token, User, Workspace, row_dict
from ..errors import ServiceError
from ..security import ROLE_PERMISSIONS, audit
from .dependencies import Identity

router = APIRouter()


class LoginInput(Contract):
    email: str = Field(min_length=3, max_length=254)
    password: str = Field(min_length=1, max_length=1024)

    @field_validator("email")
    @classmethod
    def email_syntax(cls, value):
        if "@" not in value or any(c.isspace() for c in value.strip()):
            raise ValueError("Enter a valid email address")
        return value.strip().lower()


class SetupInput(LoginInput):
    setup_token: str = Field(min_length=1, max_length=300)
    name: str = Field(min_length=1, max_length=120)
    workspace_name: str = Field(default="My workspace", min_length=1, max_length=120)


class MemberInput(Contract):
    email: str = Field(min_length=3, max_length=254)
    name: str = Field(min_length=1, max_length=120)
    password: str | None = Field(default=None, max_length=1024)
    role: str = "editor"

    @field_validator("email")
    @classmethod
    def email_syntax(cls, value):
        return LoginInput.email_syntax(value)


class RoleInput(Contract):
    role: str


class WorkspaceInput(Contract):
    name: str = Field(min_length=1, max_length=120)


class KeyInput(Contract):
    name: str = Field(min_length=1, max_length=120)
    permissions: list[str] = Field(default_factory=lambda: ["read", "execute"])
    expires_in_days: int = Field(default=30, ge=1, le=365)


class CredentialInput(Contract):
    name: str = Field(min_length=1, max_length=120)
    value: str = Field(min_length=1, max_length=20_000)


def session_response(request: Request, response: Response, raw: str):
    response.set_cookie(
        "eivon_session",
        raw,
        httponly=True,
        secure=request.app.state.settings.secure_cookies,
        samesite="strict",
        max_age=86400,
        path="/",
    )
    principal = request.app.state.security.authenticate(raw)
    return {
        **request.app.state.security.identity(principal),
        "csrf_token": request.app.state.security.csrf(raw),
    }


@router.get("/setup")
def setup_status(request: Request):
    return {
        "initialized": request.app.state.security.initialized(),
        "name": "Eivon",
        "version": "0.1.0",
    }


@router.post("/setup", status_code=201)
def setup(payload: SetupInput, request: Request, response: Response):
    security = request.app.state.security
    security.setup(
        payload.setup_token, payload.email, payload.name, payload.password, payload.workspace_name
    )
    raw = security.login(
        payload.email, payload.password, request.client.host if request.client else "local"
    )
    return session_response(request, response, raw)


@router.post("/auth/login")
def login(payload: LoginInput, request: Request, response: Response):
    raw = request.app.state.security.login(
        payload.email, payload.password, request.client.host if request.client else "local"
    )
    return session_response(request, response, raw)


@router.get("/auth/me")
def me(request: Request, identity: Identity):
    result = request.app.state.security.identity(identity)
    if not identity.api_key:
        result["csrf_token"] = request.app.state.security.csrf(request.cookies["eivon_session"])
    return result


@router.get("/auth/session")
def session_csrf(request: Request):
    return {
        "csrf_token": request.app.state.security.session_csrf(
            request.cookies.get("eivon_session", "")
        )
    }


@router.post("/auth/logout", status_code=204)
def logout(request: Request, response: Response):
    # A revoked workspace membership must not prevent invalidating a browser session.
    raw = request.cookies.get("eivon_session", "")
    if raw:
        security = request.app.state.security
        if not hmac.compare_digest(request.headers.get("x-csrf-token", ""), security.csrf(raw)):
            raise ServiceError("csrf_failed", "Refresh the page and try again", 403)
        security.logout_session(raw)
    response.delete_cookie("eivon_session", path="/")


@router.post("/workspaces", status_code=201)
def create_workspace(payload: WorkspaceInput, request: Request, identity: Identity):
    identity.require("admin")
    with request.app.state.database.transaction() as db:
        item = Workspace(name=payload.name)
        db.add(item)
        db.flush()
        db.add(Member(workspace_id=item.id, user_id=identity.user_id, role="owner"))
        audit(db, identity, "workspace.create", item.id)
        return row_dict(item)


@router.patch("/workspaces/{workspace_id}")
def rename_workspace(
    workspace_id: str, payload: WorkspaceInput, request: Request, identity: Identity
):
    identity.require("admin")
    if workspace_id != identity.workspace_id:
        raise ServiceError("not_found", "Workspace not found", 404)
    with request.app.state.database.transaction() as db:
        item = db.get(Workspace, workspace_id)
        item.name = payload.name
        audit(db, identity, "workspace.rename", workspace_id)
        db.flush()
        return row_dict(item)


@router.get("/members")
def members(request: Request, identity: Identity):
    identity.require("admin")
    with request.app.state.database.transaction() as db:
        rows = db.execute(
            select(User, Member.role)
            .join(Member, Member.user_id == User.id)
            .where(Member.workspace_id == identity.workspace_id)
        )
        return {
            "items": [
                {"user_id": u.id, "email": u.email, "name": u.name, "role": role}
                for u, role in rows
            ]
        }


@router.post("/members", status_code=201)
def add_member(payload: MemberInput, request: Request, identity: Identity):
    return request.app.state.security.add_member(identity, **payload.model_dump())


@router.patch("/members/{user_id}")
def update_member(user_id: str, payload: RoleInput, request: Request, identity: Identity):
    identity.require("admin")
    if payload.role not in ROLE_PERMISSIONS or payload.role == "owner":
        raise ServiceError("invalid_role", "Choose admin, editor, operator or viewer")
    with request.app.state.database.transaction() as db:
        item = db.get(Member, (identity.workspace_id, user_id))
        if item is None:
            raise ServiceError("not_found", "Member not found", 404)
        if item.role == "owner" or user_id == identity.user_id:
            raise ServiceError(
                "protected_member", "Owner and self-role changes are not permitted", 409
            )
        if identity.role != "owner" and (item.role == "admin" or payload.role == "admin"):
            raise ServiceError("forbidden", "Only an owner may change administrator roles", 403)
        item.role = payload.role
        audit(db, identity, "member.role", user_id, role=payload.role)
        return {"user_id": user_id, "role": payload.role}


@router.delete("/members/{user_id}", status_code=204)
def remove_member(user_id: str, request: Request, identity: Identity):
    identity.require("admin")
    with request.app.state.database.transaction() as db:
        item = db.get(Member, (identity.workspace_id, user_id))
        if item is None:
            raise ServiceError("not_found", "Member not found", 404)
        if (
            item.role == "owner"
            or user_id == identity.user_id
            or (item.role == "admin" and identity.role != "owner")
        ):
            raise ServiceError("protected_member", "This member cannot be removed by you", 403)
        db.delete(item)
        db.execute(
            delete(Token).where(
                Token.user_id == user_id, Token.workspace_id == identity.workspace_id
            )
        )
        audit(db, identity, "member.remove", user_id)


@router.get("/api-keys")
def api_keys(request: Request, identity: Identity):
    identity.require("admin")
    with request.app.state.database.transaction() as db:
        rows = db.scalars(
            select(Token)
            .where(Token.workspace_id == identity.workspace_id, Token.kind == "api")
            .order_by(Token.created_at.desc())
        )
        return {"items": [row_dict(t, ("digest",)) for t in rows]}


@router.post("/api-keys", status_code=201)
def create_key(payload: KeyInput, request: Request, identity: Identity):
    return request.app.state.security.create_api_key(
        identity, payload.name, payload.permissions, payload.expires_in_days
    )


@router.delete("/api-keys/{key_id}", status_code=204)
def delete_key(key_id: str, request: Request, identity: Identity):
    identity.require("admin")
    with request.app.state.database.transaction() as db:
        item = db.get(Token, key_id)
        if item is None or item.workspace_id != identity.workspace_id or item.kind != "api":
            raise ServiceError("not_found", "API key not found", 404)
        db.delete(item)
        audit(db, identity, "api_key.revoke", key_id)


@router.get("/credentials")
def credentials(request: Request, identity: Identity):
    identity.require("read")
    with request.app.state.database.transaction() as db:
        rows = db.scalars(
            select(Credential).where(Credential.workspace_id == identity.workspace_id)
        )
        return {"items": [row_dict(c, ("encrypted_value",)) for c in rows]}


@router.post("/credentials", status_code=201)
def create_credential(payload: CredentialInput, request: Request, identity: Identity):
    return request.app.state.security.save_credential(identity, **payload.model_dump())


@router.put("/credentials/{credential_id}")
def update_credential(
    credential_id: str, payload: CredentialInput, request: Request, identity: Identity
):
    return request.app.state.security.save_credential(
        identity, credential_id=credential_id, **payload.model_dump()
    )
