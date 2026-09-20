"""Small deterministic lexical knowledge store for the baseline release."""

from __future__ import annotations

import hashlib
import re
from typing import Any

from sqlalchemy import select

from .db import Chunk, Collection, Database, Document, row_dict
from .errors import ServiceError
from .security import Principal, audit


def terms(value: str) -> dict[str, int]:
    result: dict[str, int] = {}
    for token in re.findall(r"[\w\u4e00-\u9fff]{2,}", value.lower()):
        result[token] = result.get(token, 0) + 1
    return result


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
    def __init__(self, database: Database):
        self.database = database

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

    def create_collection(self, principal: Principal, name: str, description: str) -> dict:
        principal.require("write")
        with self.database.transaction() as db:
            item = Collection(
                workspace_id=principal.workspace_id, name=name, description=description
            )
            db.add(item)
            db.flush()
            audit(db, principal, "knowledge.collection.create", item.id)
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
                        document_id=document.id, position=position, content=part, terms=terms(part)
                    )
                )
            audit(db, principal, "knowledge.document.index", document.id)
            return row_dict(document, ("content",))

    def search(
        self, principal: Principal, collection_ids: list[str], query: str, limit: int = 8
    ) -> list[dict[str, Any]]:
        principal.require("read")
        query_terms = terms(query)
        if not query_terms:
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
                score = sum(
                    count * chunk.terms.get(token, 0) for token, count in query_terms.items()
                )
                if score:
                    scored.append((score, chunk, document))
            scored.sort(key=lambda value: (-value[0], value[2].id, value[1].position))
            return [
                {
                    "chunk_id": chunk.id,
                    "document_id": document.id,
                    "title": document.title,
                    "content": chunk.content,
                    "source_uri": document.source_uri,
                    "score": score,
                }
                for score, chunk, document in scored[:limit]
            ]

    def search_for_run(
        self, workspace_id: str, collection_ids: list[str], query: str, limit: int = 8
    ) -> list[dict[str, Any]]:
        """Worker path: the Run release already passed workspace authorization."""
        principal = Principal("run-worker", workspace_id, "worker", frozenset({"read"}))
        return self.search(principal, collection_ids, query, limit)
