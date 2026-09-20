from __future__ import annotations

from fastapi import APIRouter, Query, Request
from pydantic import Field

from eivon.core.contracts import Contract

from .dependencies import Identity

router = APIRouter()


class EvaluationSetInput(Contract):
    name: str = Field(min_length=1, max_length=160)
    cases: list[dict] = Field(min_length=1, max_length=500)


class EvaluationRunInput(Contract):
    resource_id: str
    version: int | None = Field(default=None, ge=1)
    timeout_seconds: int = Field(default=300, ge=5, le=3600)


@router.get("/evaluations")
def list_sets(
    request: Request,
    identity: Identity,
    offset: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=200),
):
    return request.app.state.evaluations.list(identity, offset, limit)


@router.post("/evaluations", status_code=201)
def create_set(payload: EvaluationSetInput, request: Request, identity: Identity):
    return request.app.state.evaluations.create(identity, payload.name, payload.cases)


@router.get("/evaluations/{evaluation_id}")
def get_set(evaluation_id: str, request: Request, identity: Identity):
    return request.app.state.evaluations.get(identity, evaluation_id)


@router.post("/evaluations/{evaluation_id}/run", status_code=202)
def run_set(evaluation_id: str, payload: EvaluationRunInput, request: Request, identity: Identity):
    return request.app.state.evaluations.start(
        identity, evaluation_id, payload.resource_id, payload.version, payload.timeout_seconds
    )


@router.get("/evaluation-jobs/{job_id}")
def get_job(job_id: str, request: Request, identity: Identity):
    return request.app.state.evaluations.job(identity, job_id)
