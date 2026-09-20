"""Versioned resource authoring and immutable dependency resolution."""

from __future__ import annotations

import hashlib
import json
import re
import time
from typing import Any

from jsonschema import Draft202012Validator
from jsonschema.exceptions import SchemaError
from pydantic import ValidationError
from sqlalchemy import func, select, update
from sqlalchemy.exc import IntegrityError

from eivon.core.contracts import RESOURCE_SCHEMAS

from .db import Collection, Credential, Database, Resource, ResourceVersion, row_dict
from .errors import ServiceError
from .security import Principal, audit

REF_KINDS = {
    "model_ref": "model",
    "model_refs": "model",
    "tool_refs": "tool",
    "tool_ref": "tool",
    "skill_refs": "skill",
    "prompt_refs": "prompt",
    "workflow_refs": "workflow",
    "bundle_refs": "bundle",
}


def canonical(value: Any) -> str:
    return json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False
    )


def schema_check(schema: dict) -> None:
    def visit(value):
        if isinstance(value, dict):
            for key, child in value.items():
                if key in {"$ref", "$dynamicRef"} and (
                    not isinstance(child, str) or not child.startswith("#")
                ):
                    raise ServiceError(
                        "invalid_schema", "Only local JSON Schema references are allowed"
                    )
                visit(child)
        elif isinstance(value, list):
            for child in value:
                visit(child)

    visit(schema)
    try:
        Draft202012Validator.check_schema(schema)
    except SchemaError as exc:
        raise ServiceError("invalid_schema", exc.message) from exc


def validate_spec(kind: str, value: dict) -> dict:
    if kind not in RESOURCE_SCHEMAS:
        raise ServiceError("invalid_kind", "Unknown resource kind")
    try:
        spec = RESOURCE_SCHEMAS[kind].model_validate(value).model_dump(mode="json")
    except ValidationError as exc:
        raise ServiceError(
            "invalid_spec",
            "Resource does not match its schema",
            422,
            json.loads(exc.json(include_url=False)),
        ) from exc
    if len(canonical(spec).encode()) > 1_000_000:
        raise ServiceError("resource_too_large", "Resource exceeds 1 MB", 413)

    def walk(value):
        if isinstance(value, dict):
            for key, child in value.items():
                if key.endswith("schema") and isinstance(child, dict):
                    schema_check(child)
                walk(child)
        elif isinstance(value, list):
            for child in value:
                walk(child)

    walk(spec)
    if kind == "skill":
        for path, content in spec["references"].items():
            if (
                path.startswith(("/", "\\"))
                or ".." in path.replace("\\", "/").split("/")
                or len(content) > 100_000
            ):
                raise ServiceError(
                    "invalid_reference",
                    "Skill references require safe relative names and bounded text",
                )
    if kind == "tool" and spec["adapter"] in {"http", "mcp"}:
        if not isinstance(spec["config"].get("url"), str):
            raise ServiceError("invalid_spec", "HTTP and MCP tools require config.url")
        if any(
            k.lower() in {"authorization", "cookie", "x-api-key"}
            for k in spec["config"].get("headers", {})
        ):
            raise ServiceError(
                "invalid_spec", "Use a credential reference instead of secret headers"
            )
    return spec


class Resources:
    def __init__(self, database: Database):
        self.database = database

    @staticmethod
    def _get(db, principal: Principal, resource_id: str) -> Resource:
        resource = db.get(Resource, resource_id)
        if resource is None or resource.workspace_id != principal.workspace_id:
            raise ServiceError("not_found", "Resource not found", 404)
        return resource

    def list(
        self,
        principal: Principal,
        kind: str | None,
        offset: int = 0,
        limit: int = 50,
        search: str = "",
        archived: bool = False,
    ) -> dict:
        principal.require("read")
        filters = [Resource.workspace_id == principal.workspace_id, Resource.archived.is_(archived)]
        if kind:
            filters.append(Resource.kind == kind)
        if search:
            escaped = search.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
            filters.append(Resource.name.ilike(f"%{escaped}%", escape="\\"))
        with self.database.transaction() as db:
            total = db.scalar(select(func.count()).select_from(Resource).where(*filters))
            rows = db.scalars(
                select(Resource)
                .where(*filters)
                .order_by(Resource.updated_at.desc(), Resource.id)
                .offset(offset)
                .limit(limit)
            )
            return {
                "items": [row_dict(r) for r in rows],
                "total": total,
                "offset": offset,
                "limit": limit,
            }

    def get(self, principal: Principal, resource_id: str) -> dict:
        principal.require("read")
        with self.database.transaction() as db:
            return row_dict(self._get(db, principal, resource_id))

    def create(self, principal: Principal, kind: str, name: str, slug: str, spec: dict) -> dict:
        principal.require("write")
        if not re.fullmatch(r"[a-z][a-z0-9_.-]{1,99}", slug):
            raise ServiceError(
                "invalid_slug", "Use 2–100 lowercase letters, digits, dots, underscores or hyphens"
            )
        spec = validate_spec(kind, spec)
        try:
            with self.database.transaction() as db:
                item = Resource(
                    workspace_id=principal.workspace_id, kind=kind, name=name, slug=slug, draft=spec
                )
                db.add(item)
                db.flush()
                audit(db, principal, "resource.create", item.id, kind=kind)
                return row_dict(item)
        except IntegrityError as exc:
            raise ServiceError("conflict", "This resource slug already exists", 409) from exc

    def update(
        self, principal: Principal, resource_id: str, revision: int, name: str, spec: dict
    ) -> dict:
        principal.require("write")
        with self.database.transaction() as db:
            item = self._get(db, principal, resource_id)
            normalized = validate_spec(item.kind, spec)
            changed = db.execute(
                update(Resource)
                .where(Resource.id == item.id, Resource.revision == revision)
                .values(name=name, draft=normalized, revision=revision + 1, updated_at=time.time())
            )
            if changed.rowcount != 1:
                raise ServiceError(
                    "revision_conflict", "This draft changed. Reload before saving", 409
                )
            db.refresh(item)
            audit(db, principal, "resource.update", item.id, revision=item.revision)
            return row_dict(item)

    def versions(self, principal: Principal, resource_id: str) -> list[dict]:
        principal.require("read")
        with self.database.transaction() as db:
            self._get(db, principal, resource_id)
            return [
                row_dict(v, ("snapshot",))
                for v in db.scalars(
                    select(ResourceVersion)
                    .where(ResourceVersion.resource_id == resource_id)
                    .order_by(ResourceVersion.version.desc())
                )
            ]

    def version(self, principal: Principal, resource_id: str, version: int) -> dict:
        principal.require("read")
        with self.database.transaction() as db:
            self._get(db, principal, resource_id)
            item = db.get(ResourceVersion, (resource_id, version))
            if item is None:
                raise ServiceError("not_found", "Resource version not found", 404)
            return row_dict(item)

    def preview(self, principal: Principal, resource_id: str, revision: int | None = None) -> dict:
        principal.require("write")
        with self.database.transaction() as db:
            item = self._get(db, principal, resource_id)
            if revision is not None and revision != item.revision:
                raise ServiceError(
                    "revision_conflict", "This draft changed. Reload before validating", 409
                )
            return self._snapshot(db, principal, item, item.draft)

    def publish(self, principal: Principal, resource_id: str, revision: int) -> dict:
        principal.require("write")
        with self.database.transaction() as db:
            item = self._get(db, principal, resource_id)
            if item.archived:
                raise ServiceError("archived", "Restore this resource before publishing", 409)
            if item.revision != revision:
                raise ServiceError(
                    "revision_conflict", "This draft changed. Reload before publishing", 409
                )
            snapshot = self._snapshot(db, principal, item, item.draft)
            next_version = item.latest_version + 1
            changed = db.execute(
                update(Resource)
                .where(
                    Resource.id == item.id,
                    Resource.revision == revision,
                    Resource.latest_version == item.latest_version,
                )
                .values(
                    latest_version=next_version,
                    active_version=next_version,
                    revision=revision + 1,
                    updated_at=time.time(),
                )
            )
            if changed.rowcount != 1:
                raise ServiceError("revision_conflict", "Resource was published concurrently", 409)
            version = ResourceVersion(
                resource_id=item.id,
                version=next_version,
                spec=item.draft,
                snapshot=snapshot,
                digest=hashlib.sha256(canonical(snapshot).encode()).hexdigest(),
                created_by=principal.user_id,
            )
            db.add(version)
            db.flush()
            audit(
                db,
                principal,
                "resource.publish",
                item.id,
                version=next_version,
                digest=version.digest,
            )
            return {**row_dict(version), "id": item.id}

    def activate(self, principal: Principal, resource_id: str, version: int, revision: int) -> dict:
        principal.require("write")
        with self.database.transaction() as db:
            item = self._get(db, principal, resource_id)
            if db.get(ResourceVersion, (resource_id, version)) is None:
                raise ServiceError("not_found", "Version not found", 404)
            changed = db.execute(
                update(Resource)
                .where(Resource.id == item.id, Resource.revision == revision)
                .values(active_version=version, revision=revision + 1, updated_at=time.time())
            )
            if changed.rowcount != 1:
                raise ServiceError("revision_conflict", "Resource changed", 409)
            db.refresh(item)
            audit(db, principal, "resource.activate", resource_id, version=version)
            return row_dict(item)

    def archive(
        self, principal: Principal, resource_id: str, archived: bool, revision: int
    ) -> dict:
        principal.require("write")
        with self.database.transaction() as db:
            item = self._get(db, principal, resource_id)
            changed = db.execute(
                update(Resource)
                .where(Resource.id == item.id, Resource.revision == revision)
                .values(archived=archived, revision=revision + 1, updated_at=time.time())
            )
            if changed.rowcount != 1:
                raise ServiceError("revision_conflict", "Resource changed", 409)
            db.refresh(item)
            audit(
                db, principal, "resource.archive" if archived else "resource.restore", resource_id
            )
            return row_dict(item)

    def _snapshot(self, db, principal: Principal, root: Resource, spec: dict) -> dict:
        spec = validate_spec(root.kind, spec)
        resolved: dict[str, dict] = {}
        credentials: set[str] = set()
        collections: set[str] = set()
        visiting: set[str] = set()

        def reference(ref: dict, kind: str):
            key = f"{ref['id']}@{ref['version']}"
            if key in visiting:
                raise ServiceError("dependency_cycle", "Resource references contain a cycle")
            if key in resolved:
                if resolved[key]["kind"] != kind:
                    raise ServiceError("dependency_kind", "Dependency has an unexpected kind")
                return
            if len(resolved) >= 300:
                raise ServiceError(
                    "too_many_dependencies", "A release may reference at most 300 resources"
                )
            resource = self._get(db, principal, ref["id"])
            if resource.archived or resource.kind != kind:
                raise ServiceError(
                    "dependency_unavailable", f"Dependency must be an active {kind}", 409
                )
            version = db.get(ResourceVersion, (ref["id"], ref["version"]))
            if version is None:
                raise ServiceError(
                    "dependency_unpublished", "Dependency version is not published", 409
                )
            visiting.add(key)
            resolved[key] = {
                "id": resource.id,
                "slug": resource.slug,
                "name": resource.name,
                "kind": kind,
                "version": version.version,
                "spec": version.spec,
                "digest": version.digest,
            }
            walk(version.spec)
            visiting.remove(key)

        def walk(value):
            if isinstance(value, dict):
                for key, child in value.items():
                    if key in REF_KINDS:
                        for ref in child if isinstance(child, list) else [child]:
                            reference(ref, REF_KINDS[key])
                    elif key == "credential_id" and child:
                        credentials.add(child)
                    elif key == "knowledge_collection_ids":
                        collections.update(child)
                    else:
                        walk(child)
            elif isinstance(value, list):
                for child in value:
                    walk(child)

        walk(spec)
        for credential_id in credentials:
            credential = db.get(Credential, credential_id)
            if credential is None or credential.workspace_id != principal.workspace_id:
                raise ServiceError(
                    "credential_unavailable", "Referenced credential is unavailable", 409
                )
        for collection_id in collections:
            collection = db.get(Collection, collection_id)
            if collection is None or collection.workspace_id != principal.workspace_id:
                raise ServiceError(
                    "collection_unavailable", "Referenced knowledge collection is unavailable", 409
                )
        # One exact version per resource avoids ambiguous multi-bundle behavior.
        seen: dict[str, int] = {}
        for resource in resolved.values():
            previous = seen.setdefault(resource["id"], resource["version"])
            if previous != resource["version"]:
                raise ServiceError(
                    "version_conflict",
                    "Bundles reference different versions of the same resource",
                    409,
                )
        if root.kind == "agent":
            model = resolved[f"{spec['model_ref']['id']}@{spec['model_ref']['version']}"]
            if not model["spec"]["supports_tools"] and any(
                r["kind"] in {"tool", "workflow"} for r in resolved.values()
            ):
                raise ServiceError(
                    "model_capability", "This agent requires a model supporting tool calls"
                )
        return {
            "schema_version": 1,
            "root": {
                "id": root.id,
                "kind": root.kind,
                "slug": root.slug,
                "name": root.name,
                "spec": spec,
            },
            "resources": resolved,
            "knowledge_collection_ids": sorted(collections),
        }
