"""Resource CRUD and publishing API backed by the shared resource service."""

from __future__ import annotations

from fastapi import APIRouter, Query, Request
from pydantic import Field

from eivon.core.contracts import RESOURCE_SCHEMAS, Contract, ResourceKind

from .dependencies import Identity

router = APIRouter()


class CreateResource(Contract):
    kind: ResourceKind
    name: str = Field(min_length=1, max_length=160)
    slug: str = Field(min_length=2, max_length=100)
    spec: dict


class UpdateResource(Contract):
    revision: int = Field(ge=1)
    name: str = Field(min_length=1, max_length=160)
    spec: dict


class RevisionInput(Contract):
    revision: int = Field(ge=1)


class ActivateInput(RevisionInput):
    version: int = Field(ge=1)


class ArchiveInput(RevisionInput):
    archived: bool = True


@router.get("/resource-schemas")
def schemas(identity: Identity):
    identity.require("read")
    return {kind: schema.model_json_schema() for kind, schema in RESOURCE_SCHEMAS.items()}


@router.get("/resources")
def list_resources(
    request: Request,
    identity: Identity,
    kind: ResourceKind | None = None,
    offset: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=200),
    search: str = Query("", max_length=200),
    archived: bool = False,
):
    return request.app.state.resources.list(identity, kind, offset, limit, search, archived)


@router.post("/resources", status_code=201)
def create_resource(payload: CreateResource, request: Request, identity: Identity):
    return request.app.state.resources.create(identity, **payload.model_dump())


@router.get("/resources/{resource_id}")
def resource(resource_id: str, request: Request, identity: Identity):
    return request.app.state.resources.get(identity, resource_id)


@router.put("/resources/{resource_id}")
def update_resource(
    resource_id: str, payload: UpdateResource, request: Request, identity: Identity
):
    return request.app.state.resources.update(identity, resource_id, **payload.model_dump())


@router.get("/resources/{resource_id}/versions")
def versions(resource_id: str, request: Request, identity: Identity):
    return {"items": request.app.state.resources.versions(identity, resource_id)}


@router.get("/resources/{resource_id}/versions/{version}")
def version(resource_id: str, version: int, request: Request, identity: Identity):
    return request.app.state.resources.version(identity, resource_id, version)


@router.post("/resources/{resource_id}/validate")
def validate(
    resource_id: str, request: Request, identity: Identity, payload: RevisionInput | None = None
):
    snapshot = request.app.state.resources.preview(
        identity, resource_id, payload.revision if payload else None
    )
    return {"valid": True, "dependencies": len(snapshot["resources"]), "snapshot": snapshot}


@router.post("/resources/{resource_id}/publish", status_code=201)
def publish(resource_id: str, payload: RevisionInput, request: Request, identity: Identity):
    return request.app.state.resources.publish(identity, resource_id, payload.revision)


@router.post("/resources/{resource_id}/activate")
def activate(resource_id: str, payload: ActivateInput, request: Request, identity: Identity):
    return request.app.state.resources.activate(
        identity, resource_id, payload.version, payload.revision
    )


@router.post("/resources/{resource_id}/archive")
def archive(resource_id: str, payload: ArchiveInput, request: Request, identity: Identity):
    return request.app.state.resources.archive(
        identity, resource_id, payload.archived, payload.revision
    )
