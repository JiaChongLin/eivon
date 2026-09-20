"""Credentials, passwords and server-owned identity checks."""

from __future__ import annotations

import base64
import hashlib
import hmac
import os
import secrets
import time
from dataclasses import dataclass
from pathlib import Path

from cryptography.fernet import Fernet
from sqlalchemy import delete, select, update
from sqlalchemy.exc import IntegrityError

from .db import (
    AuditEvent,
    Credential,
    Database,
    LoginAttempt,
    Member,
    Meta,
    Token,
    User,
    Workspace,
    row_dict,
)
from .errors import ServiceError
from .settings import Settings

ROLE_PERMISSIONS = {
    "owner": frozenset({"read", "write", "execute", "approve", "admin"}),
    "admin": frozenset({"read", "write", "execute", "approve", "admin"}),
    "editor": frozenset({"read", "write", "execute"}),
    "operator": frozenset({"read", "execute", "approve"}),
    "viewer": frozenset({"read"}),
}


def digest(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def hash_password(password: str) -> str:
    if not 12 <= len(password) <= 1024:
        raise ServiceError("invalid_password", "Password must contain 12 to 1024 characters")
    salt = secrets.token_bytes(16)
    hashed = hashlib.scrypt(password.encode(), salt=salt, n=16384, r=8, p=1, dklen=32)
    return "scrypt$" + base64.b64encode(salt).decode() + "$" + base64.b64encode(hashed).decode()


def verify_password(password: str, stored: str) -> bool:
    if len(password) > 1024:
        return False
    try:
        algorithm, salt, expected = stored.split("$")
        if algorithm != "scrypt":
            return False
        actual = hashlib.scrypt(
            password.encode(), salt=base64.b64decode(salt), n=16384, r=8, p=1, dklen=32
        )
        return hmac.compare_digest(actual, base64.b64decode(expected))
    except (ValueError, TypeError):
        return False


def private_file(path: Path, value: str) -> str:
    """Publish a complete mode-0600 secret atomically, including multi-worker startup."""
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{secrets.token_hex(8)}")
    fd = os.open(temporary, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    try:
        with os.fdopen(fd, "w") as handle:
            handle.write(value)
            handle.flush()
            os.fsync(handle.fileno())
        try:
            os.link(temporary, path)
        except FileExistsError:
            pass
    finally:
        temporary.unlink(missing_ok=True)
    return path.read_text().strip()


@dataclass(frozen=True)
class Principal:
    user_id: str
    workspace_id: str
    role: str
    permissions: frozenset[str]
    token_id: str | None = None
    api_key: bool = False

    def require(self, permission: str) -> None:
        if permission not in self.permissions:
            raise ServiceError("forbidden", "You do not have permission for this action", 403)


def audit(db, principal: Principal | None, action: str, target_id: str | None = None, **details):
    db.add(
        AuditEvent(
            workspace_id=principal.workspace_id if principal else None,
            user_id=principal.user_id if principal else None,
            action=action,
            target_id=target_id,
            details=details,
        )
    )


class Security:
    def __init__(self, database: Database, settings: Settings):
        self.database = database
        self.settings = settings
        key = settings.secret_key or private_file(
            settings.data_dir / "secret.key", Fernet.generate_key().decode()
        )
        self.cipher = Fernet(key.encode())
        self.csrf_key = key.encode()
        self.setup_token = settings.setup_token or private_file(
            settings.data_dir / "setup-token", secrets.token_urlsafe(32)
        )
        self._dummy_password = hash_password(secrets.token_urlsafe(32))

    def initialized(self) -> bool:
        with self.database.transaction() as db:
            return db.get(Meta, "initialized").value == "true"

    def setup(self, token: str, email: str, name: str, password: str, workspace_name: str) -> dict:
        if not hmac.compare_digest(token, self.setup_token):
            raise ServiceError(
                "invalid_setup_token", "Enter the setup token from the server data directory", 403
            )
        password_hash = hash_password(password)
        with self.database.transaction() as db:
            updated = db.execute(
                update(Meta)
                .where(Meta.key == "initialized", Meta.value == "false")
                .values(value="true")
            )
            if updated.rowcount != 1:
                raise ServiceError(
                    "already_initialized", "This instance is already initialized", 409
                )
            user = User(email=email.strip().lower(), name=name, password_hash=password_hash)
            workspace = Workspace(name=workspace_name)
            db.add_all([user, workspace])
            db.flush()
            db.add(Member(workspace_id=workspace.id, user_id=user.id, role="owner"))
            audit(
                db,
                Principal(user.id, workspace.id, "owner", ROLE_PERMISSIONS["owner"]),
                "instance.setup",
                workspace.id,
            )
            return {"user_id": user.id, "workspace_id": workspace.id}

    def login(self, email: str, password: str, remote_address: str) -> str:
        email = email.strip().lower()
        # Persistent throttling survives process changes; proxy headers are not trusted here.
        key = digest(email + ":" + remote_address)
        now = time.time()
        failure = False
        with self.database.transaction() as db:
            attempt = db.get(LoginAttempt, key)
            if attempt and attempt.reset_at > now and attempt.failures >= 10:
                raise ServiceError(
                    "rate_limited", "Too many login attempts; try again in 15 minutes", 429
                )
            user = db.scalar(select(User).where(User.email == email))
            if not verify_password(password, user.password_hash if user else self._dummy_password):
                if attempt is None:
                    db.add(LoginAttempt(key=key, failures=1, reset_at=now + 900))
                elif attempt.reset_at <= now:
                    attempt.failures, attempt.reset_at = 1, now + 900
                else:
                    attempt.failures += 1
                failure = True
            else:
                if attempt:
                    db.delete(attempt)
                raw = secrets.token_urlsafe(40)
                db.add(
                    Token(
                        digest=digest(raw), user_id=user.id, kind="session", expires_at=now + 86400
                    )
                )
        if failure:
            raise ServiceError("invalid_credentials", "Email or password is incorrect", 401)
        return raw

    def csrf(self, raw_token: str) -> str:
        return hmac.new(self.csrf_key, raw_token.encode(), hashlib.sha256).hexdigest()

    def authenticate(
        self, raw_token: str, workspace_id: str | None = None, *, bearer: bool = False
    ) -> Principal:
        with self.database.transaction() as db:
            token = db.scalar(
                select(Token).where(
                    Token.digest == digest(raw_token), Token.expires_at > time.time()
                )
            )
            if (
                token is None
                or (bearer and token.kind != "api")
                or (not bearer and token.kind != "session")
            ):
                raise ServiceError("unauthorized", "Sign in to continue", 401)
            if token.kind == "api":
                if workspace_id and workspace_id != token.workspace_id:
                    raise ServiceError(
                        "forbidden", "API key is bound to a different workspace", 403
                    )
                workspace_id = token.workspace_id
            query = select(Member).where(Member.user_id == token.user_id)
            if workspace_id:
                query = query.where(Member.workspace_id == workspace_id)
            membership = db.scalar(query.order_by(Member.workspace_id))
            if membership is None:
                raise ServiceError("forbidden", "Workspace membership required", 403)
            permissions = ROLE_PERMISSIONS[membership.role]
            if token.kind == "api":
                permissions &= frozenset(token.permissions)
            return Principal(
                token.user_id,
                membership.workspace_id,
                membership.role,
                permissions,
                token.id,
                token.kind == "api",
            )

    def identity(self, principal: Principal) -> dict:
        with self.database.transaction() as db:
            user = db.get(User, principal.user_id)
            query = (
                select(Workspace, Member.role)
                .join(Member, Member.workspace_id == Workspace.id)
                .where(Member.user_id == user.id)
            )
            if principal.api_key:
                query = query.where(Workspace.id == principal.workspace_id)
            memberships = db.execute(query.order_by(Workspace.name, Workspace.id)).all()
            return {
                "user": row_dict(user, ("password_hash",)),
                "workspace_id": principal.workspace_id,
                "role": principal.role,
                "permissions": sorted(principal.permissions),
                "workspaces": [
                    {"id": w.id, "name": w.name, "role": role} for w, role in memberships
                ],
            }

    def session_csrf(self, raw_token: str) -> str:
        with self.database.transaction() as db:
            token = db.scalar(
                select(Token).where(
                    Token.digest == digest(raw_token),
                    Token.kind == "session",
                    Token.expires_at > time.time(),
                )
            )
            if token is None:
                raise ServiceError("unauthorized", "Sign in to continue", 401)
        return self.csrf(raw_token)

    def logout_session(self, raw_token: str) -> None:
        with self.database.transaction() as db:
            db.execute(
                delete(Token).where(Token.digest == digest(raw_token), Token.kind == "session")
            )

    def create_api_key(
        self, principal: Principal, name: str, permissions: list[str], days: int
    ) -> dict:
        principal.require("admin")
        if not permissions or not set(permissions).issubset(principal.permissions):
            raise ServiceError(
                "invalid_permissions",
                "Key permissions must be a non-empty subset of your permissions",
            )
        raw = "eiv_" + secrets.token_urlsafe(40)
        with self.database.transaction() as db:
            token = Token(
                digest=digest(raw),
                user_id=principal.user_id,
                workspace_id=principal.workspace_id,
                kind="api",
                name=name,
                permissions=sorted(set(permissions)),
                expires_at=time.time() + days * 86400,
            )
            db.add(token)
            db.flush()
            audit(db, principal, "api_key.create", token.id, permissions=token.permissions)
            return {**row_dict(token, ("digest",)), "secret": raw}

    def save_credential(
        self, principal: Principal, name: str, value: str, credential_id: str | None = None
    ) -> dict:
        principal.require("admin")
        with self.database.transaction() as db:
            if credential_id:
                credential = db.get(Credential, credential_id)
                if credential is None or credential.workspace_id != principal.workspace_id:
                    raise ServiceError("not_found", "Credential not found", 404)
                credential.name, credential.encrypted_value = (
                    name,
                    self.cipher.encrypt(value.encode()).decode(),
                )
                credential.updated_at = time.time()
            else:
                credential = Credential(
                    workspace_id=principal.workspace_id,
                    name=name,
                    encrypted_value=self.cipher.encrypt(value.encode()).decode(),
                )
                db.add(credential)
            db.flush()
            audit(
                db,
                principal,
                "credential.rotate" if credential_id else "credential.create",
                credential.id,
            )
            return row_dict(credential, ("encrypted_value",))

    def credential_value(self, workspace_id: str, credential_id: str | None) -> str | None:
        if not credential_id:
            return None
        with self.database.transaction() as db:
            credential = db.get(Credential, credential_id)
            if credential is None or credential.workspace_id != workspace_id:
                raise ServiceError(
                    "credential_unavailable", "The configured credential is unavailable", 409
                )
            return self.cipher.decrypt(credential.encrypted_value.encode()).decode()

    def add_member(
        self, principal: Principal, email: str, name: str, password: str | None, role: str
    ) -> dict:
        principal.require("admin")
        if role not in ROLE_PERMISSIONS or role == "owner":
            raise ServiceError("invalid_role", "Choose admin, editor, operator or viewer")
        if principal.role != "owner" and role == "admin":
            raise ServiceError("forbidden", "Only an owner can grant administrator access", 403)
        try:
            with self.database.transaction() as db:
                user = db.scalar(select(User).where(User.email == email.lower().strip()))
                if user is None:
                    if not password:
                        raise ServiceError(
                            "password_required", "An initial password is required for a new user"
                        )
                    user = User(
                        email=email.lower().strip(),
                        name=name,
                        password_hash=hash_password(password),
                    )
                    db.add(user)
                    db.flush()
                if db.get(Member, (principal.workspace_id, user.id)):
                    raise ServiceError("already_member", "This user is already a member", 409)
                db.add(Member(workspace_id=principal.workspace_id, user_id=user.id, role=role))
                audit(db, principal, "member.add", user.id, role=role)
                return {"user_id": user.id, "email": user.email, "name": user.name, "role": role}
        except IntegrityError as exc:
            raise ServiceError(
                "conflict", "A member with this email was added concurrently", 409
            ) from exc
