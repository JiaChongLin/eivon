"""Workspace-scoped knowledge indexing with lexical, semantic and hybrid retrieval."""

from __future__ import annotations

import hashlib
import math
import re
from typing import Any

import httpx
from sqlalchemy import select

from eivon.adapters.network import check_destination
from eivon.core.contracts import ConnectionSpec
from eivon.server.resources import validate_spec

from .db import (
    Chunk,
    Collection,
    Credential,
    Database,
    Document,
    Resource,
    ResourceVersion,
    row_dict,
)
from .errors import ServiceError
from .security import Principal, audit


def terms(value: str) -> dict[str, int]:
    result: dict[str, int] = {}
    for token in re.findall(r"[\w\u4e00-\u9fff]{2,}", value.lower()):
        result[token] = result.get(token, 0) + 1
    return result


def embedding(value: str, dimensions: int = 96) -> list[float]:
    """Stable local embedding for offline installs; uses token and character features."""
    vector = [0.0] * dimensions
    features = list(terms(value)) + [
        value.lower()[i : i + 3] for i in range(max(0, len(value) - 2))
    ]
    for feature in features:
        digest = hashlib.blake2b(feature.encode(), digest_size=8).digest()
        index = int.from_bytes(digest[:4], "big") % dimensions
        sign = 1.0 if digest[4] & 1 else -1.0
        vector[index] += sign
    norm = math.sqrt(sum(item * item for item in vector)) or 1.0
    return [round(item / norm, 8) for item in vector]


def similarity(left: list[float], right: list[float]) -> float:
    if not left or not right or len(left) != len(right):
        return 0.0
    return max(0.0, min(1.0, sum(a * b for a, b in zip(left, right, strict=True))))


def chunks(value: str, size: int = 1200, overlap: int = 120) -> list[str]:
    if len(value) <= size:
        return [value]
    result = []
    step = max(1, size - overlap)
    for start in range(0, len(value), step):
        part = value[start : start + size]
        if part:
            result.append(part)
        if start + size >= len(value):
            break
    return result


class Knowledge:
    def __init__(self, database: Database, settings=None, security=None):
        self.database, self.settings, self.security = database, settings, security

    def _connection(self, db, principal, connection_id: str | None):
        if not connection_id:
            return None
        resource = db.get(Resource, connection_id)
        if resource is None or resource.workspace_id != principal.workspace_id:
            raise ServiceError("not_found", "Connection not found", 404)
        if resource.kind != "connection":
            raise ServiceError("connection_unavailable", "Resource is not a connection", 422)
        if resource.archived or not resource.active_version:
            raise ServiceError(
                "connection_unavailable", "Connection must have an active release", 409
            )
        release = db.get(ResourceVersion, (resource.id, resource.active_version))
        validate_spec("connection", release.spec)
        return resource, release

    def connections(self, principal: Principal) -> list[dict]:
        principal.require("read")
        with self.database.transaction() as db:
            rows = db.scalars(
                select(Resource)
                .where(
                    Resource.workspace_id == principal.workspace_id,
                    Resource.kind == "connection",
                    Resource.archived.is_(False),
                )
                .order_by(Resource.name, Resource.id)
            )
            return [
                {
                    "id": row.id,
                    "name": row.name,
                    "active_version": row.active_version,
                    "slug": row.slug,
                }
                for row in rows
            ]

    def test_connection(self, principal: Principal, connection_id: str) -> dict:
        principal.require("execute")
        with self.database.transaction() as db:
            resource, release = self._connection(db, principal, connection_id)
            spec = ConnectionSpec.model_validate(release.spec)
            check_destination(spec.base_url, self.settings.allowed_hosts if self.settings else ())
            if spec.credential_id:
                credential = db.get(Credential, spec.credential_id)
                if credential is None or credential.workspace_id != principal.workspace_id:
                    raise ServiceError(
                        "credential_unavailable", "Connection credential is unavailable", 409
                    )
            return {
                "connection_id": resource.id,
                "version": release.version,
                "status": "configured",
                "adapter": spec.adapter,
                "base_url": spec.base_url,
            }

    def sync_collection(self, principal: Principal, collection_id: str) -> dict:
        principal.require("write")
        principal.require("execute")
        with self.database.transaction() as db:
            collection = db.get(Collection, collection_id)
            if collection is None or collection.workspace_id != principal.workspace_id:
                raise ServiceError("not_found", "Knowledge collection not found", 404)
            if not collection.connection_id:
                raise ServiceError(
                    "connection_unavailable", "Collection has no sync connection", 409
                )
            resource, release = self._connection(db, principal, collection.connection_id)
            if collection.connection_version != release.version:
                raise ServiceError(
                    "connection_changed", "Publish and rebind the collection before syncing", 409
                )
            spec = ConnectionSpec.model_validate(release.spec)
            headers = {}
            if spec.credential_id and self.security:
                secret = self.security.credential_value(principal.workspace_id, spec.credential_id)
                if secret:
                    headers["Authorization"] = "Bearer " + secret
        try:
            with httpx.Client(timeout=spec.timeout_seconds, follow_redirects=False) as client:
                response = client.get(
                    check_destination(
                        spec.base_url, self.settings.allowed_hosts if self.settings else ()
                    ),
                    headers=headers,
                )
                response.raise_for_status()
                if len(response.content) > 5_000_000:
                    raise ServiceError("source_too_large", "Knowledge source exceeds 5 MB", 413)
                payload = response.json()
        except ServiceError:
            raise
        except (httpx.HTTPError, ValueError) as exc:
            raise ServiceError(
                "connection_failed", "Knowledge connection request failed", 502
            ) from exc
        documents = payload.get("documents") if isinstance(payload, dict) else payload
        if not isinstance(documents, list) or len(documents) > 500:
            raise ServiceError(
                "invalid_source", "Source must return a list or {documents: [...]}", 422
            )
        imported = skipped = 0
        with self.database.transaction() as db:
            for item in documents:
                if (
                    not isinstance(item, dict)
                    or not isinstance(item.get("title"), str)
                    or not isinstance(item.get("content"), str)
                ):
                    raise ServiceError(
                        "invalid_source", "Each source document requires title and content", 422
                    )
                content = item["content"]
                if not content.strip() or len(content) > 5_000_000:
                    raise ServiceError(
                        "invalid_document", "Source document content is invalid", 422
                    )
                digest = hashlib.sha256(content.encode()).hexdigest()
                if db.scalar(
                    select(Document).where(
                        Document.collection_id == collection_id, Document.digest == digest
                    )
                ):
                    skipped += 1
                    continue
                document = Document(
                    collection_id=collection_id,
                    title=item["title"][:200],
                    content=content,
                    source_uri=str(item.get("source_uri") or spec.base_url)[:2048],
                    digest=digest,
                    status="indexed",
                )
                db.add(document)
                db.flush()
                for position, part in enumerate(chunks(content)):
                    db.add(
                        Chunk(
                            document_id=document.id,
                            position=position,
                            content=part,
                            terms=terms(part),
                            embedding=embedding(part),
                        )
                    )
                imported += 1
            audit(
                db,
                principal,
                "knowledge.collection.sync",
                collection_id,
                imported=imported,
                skipped=skipped,
                connection_id=collection.connection_id,
            )
        return {
            "collection_id": collection_id,
            "connection_id": resource.id,
            "connection_version": release.version,
            "imported": imported,
            "skipped": skipped,
        }

    def collections(self, principal: Principal) -> list[dict]:
        principal.require("read")
        with self.database.transaction() as db:
            return [
                row_dict(x)
                for x in db.scalars(
                    select(Collection)
                    .where(Collection.workspace_id == principal.workspace_id)
                    .order_by(Collection.created_at.desc())
                )
            ]

    def create_collection(
        self, principal: Principal, name: str, description: str, connection_id: str | None = None
    ) -> dict:
        principal.require("write")
        with self.database.transaction() as db:
            connection = self._connection(db, principal, connection_id)
            item = Collection(
                workspace_id=principal.workspace_id,
                name=name,
                description=description,
                connection_id=connection[0].id if connection else None,
                connection_version=connection[1].version if connection else None,
            )
            db.add(item)
            db.flush()
            audit(
                db,
                principal,
                "knowledge.collection.create",
                item.id,
                connection_id=item.connection_id,
            )
            return row_dict(item)

    def add_document(
        self,
        principal: Principal,
        collection_id: str,
        title: str,
        content: str,
        source_uri: str = "",
    ) -> dict:
        principal.require("write")
        if not content.strip() or len(content) > 5_000_000:
            raise ServiceError(
                "invalid_document", "Document must contain 1 to 5,000,000 characters", 422
            )
        with self.database.transaction() as db:
            collection = db.get(Collection, collection_id)
            if collection is None or collection.workspace_id != principal.workspace_id:
                raise ServiceError("not_found", "Knowledge collection not found", 404)
            document = Document(
                collection_id=collection.id,
                title=title,
                content=content,
                source_uri=source_uri,
                digest=hashlib.sha256(content.encode()).hexdigest(),
                status="indexed",
            )
            db.add(document)
            db.flush()
            for position, part in enumerate(chunks(content)):
                db.add(
                    Chunk(
                        document_id=document.id,
                        position=position,
                        content=part,
                        terms=terms(part),
                        embedding=embedding(part),
                    )
                )
            audit(db, principal, "knowledge.document.index", document.id)
            return row_dict(document, ("content",))

    def search(
        self,
        principal: Principal,
        collection_ids: list[str],
        query: str,
        limit: int = 8,
        mode: str = "hybrid",
    ) -> list[dict[str, Any]]:
        principal.require("read")
        if mode not in {"lexical", "semantic", "hybrid"}:
            raise ServiceError("invalid_search_mode", "Choose lexical, semantic or hybrid", 422)
        query_terms, query_embedding = terms(query), embedding(query)
        if not query_terms and mode == "lexical":
            return []
        with self.database.transaction() as db:
            allowed = list(
                db.scalars(
                    select(Collection).where(
                        Collection.workspace_id == principal.workspace_id,
                        Collection.id.in_(collection_ids),
                    )
                )
            )
            allowed_ids = {item.id for item in allowed}
            if len(allowed_ids) != len(set(collection_ids)):
                raise ServiceError(
                    "collection_unavailable",
                    "A knowledge collection is not available in this workspace",
                    403,
                )
            rows = db.execute(
                select(Chunk, Document)
                .join(Document, Document.id == Chunk.document_id)
                .where(
                    Chunk.document_id.in_(
                        select(Document.id).where(Document.collection_id.in_(allowed_ids))
                    )
                )
            )
            scored = []
            for chunk, document in rows:
                lexical = sum(
                    count * chunk.terms.get(token, 0) for token, count in query_terms.items()
                )
                semantic = similarity(chunk.embedding or embedding(chunk.content), query_embedding)
                score = (
                    semantic
                    if mode == "semantic"
                    else float(lexical)
                    if mode == "lexical"
                    else semantic * 0.7 + min(1.0, lexical / max(1, len(query_terms))) * 0.3
                )
                if score > 0:
                    scored.append((score, lexical, semantic, chunk, document))
            scored.sort(key=lambda value: (-value[0], value[4].id, value[3].position))
            return [
                {
                    "chunk_id": chunk.id,
                    "document_id": document.id,
                    "title": document.title,
                    "content": chunk.content,
                    "source_uri": document.source_uri,
                    "score": round(score, 6),
                    "lexical_score": lexical,
                    "semantic_score": round(semantic, 6),
                    "collection_id": document.collection_id,
                }
                for score, lexical, semantic, chunk, document in scored[:limit]
            ]

    def search_for_run(
        self, workspace_id: str, collection_ids: list[str], query: str, limit: int = 8
    ) -> list[dict[str, Any]]:
        principal = Principal("run-worker", workspace_id, "worker", frozenset({"read"}))
        return self.search(principal, collection_ids, query, limit)
