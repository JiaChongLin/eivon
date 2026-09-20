from fastapi import APIRouter, Request
from pydantic import Field

from eivon.core.contracts import Contract

from .dependencies import Identity

router = APIRouter()


class CollectionInput(Contract):
    name: str = Field(min_length=1, max_length=160)
    description: str = Field(default="", max_length=4000)
    connection_id: str | None = None


class DocumentInput(Contract):
    collection_id: str
    title: str = Field(min_length=1, max_length=200)
    content: str = Field(min_length=1, max_length=5_000_000)
    source_uri: str = Field(default="", max_length=2048)


class SearchInput(Contract):
    collection_ids: list[str] = Field(min_length=1, max_length=50)
    query: str = Field(min_length=1, max_length=2000)
    limit: int = Field(default=8, ge=1, le=50)
    mode: str = Field(default="hybrid", pattern="^(lexical|semantic|hybrid)$")


@router.get("/knowledge/connections")
def connections(request: Request, identity: Identity):
    return {"items": request.app.state.knowledge.connections(identity)}


@router.post("/knowledge/connections/{connection_id}/test")
def test_connection(connection_id: str, request: Request, identity: Identity):
    return request.app.state.knowledge.test_connection(identity, connection_id)


@router.get("/knowledge/collections")
def collections(request: Request, identity: Identity):
    return {"items": request.app.state.knowledge.collections(identity)}


@router.post("/knowledge/collections", status_code=201)
def create_collection(payload: CollectionInput, request: Request, identity: Identity):
    return request.app.state.knowledge.create_collection(identity, **payload.model_dump())


@router.post("/knowledge/documents", status_code=201)
def document(payload: DocumentInput, request: Request, identity: Identity):
    return request.app.state.knowledge.add_document(identity, **payload.model_dump())


@router.post("/knowledge/search")
def search(payload: SearchInput, request: Request, identity: Identity):
    return {"items": request.app.state.knowledge.search(identity, **payload.model_dump())}
