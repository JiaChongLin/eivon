from __future__ import annotations

from typing import Literal

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


class ResultReviewInput(Contract):
    score: float = Field(ge=0, le=1, allow_inf_nan=False)
    note: str = Field(min_length=1, max_length=4000)


class ProposalInput(Contract):
    resource_id: str
    revision: int = Field(ge=1)
    text: str = Field(min_length=1, max_length=200_000)
    rationale: str = Field(min_length=1, max_length=4000)


class ProposalDecisionInput(Contract):
    decision: Literal["accepted", "rejected"]
    note: str = Field(min_length=1, max_length=4000)


@router.get("/evaluations/{evaluation_id}/jobs")
def list_jobs(
    evaluation_id: str,
    request: Request,
    identity: Identity,
    offset: int = Query(0, ge=0),
    limit: int = Query(25, ge=1, le=100),
):
    return request.app.state.evaluations.jobs(identity, evaluation_id, offset, limit)


@router.get("/evaluation-comparison")
def compare_jobs(request: Request, identity: Identity, baseline: str, candidate: str):
    return request.app.state.evaluations.compare(identity, baseline, candidate)


@router.post("/evaluation-jobs/{job_id}/results/{result_id}/reviews", status_code=201)
def review_result(
    job_id: str, result_id: str, payload: ResultReviewInput, request: Request, identity: Identity
):
    return request.app.state.evaluations.review_result(
        identity, job_id, result_id, payload.score, payload.note
    )


@router.get("/evaluation-jobs/{job_id}/reflection")
def reflect(job_id: str, request: Request, identity: Identity):
    return request.app.state.evaluations.reflection(identity, job_id)


@router.post("/evaluation-jobs/{job_id}/analysis")
async def analyze(job_id: str, request: Request, identity: Identity):
    return await request.app.state.evaluations.analyze(identity, job_id)


@router.post("/evaluation-jobs/{job_id}/proposals", status_code=201)
def propose(job_id: str, payload: ProposalInput, request: Request, identity: Identity):
    return request.app.state.evaluations.propose(identity, job_id, **payload.model_dump())


@router.post("/evaluation-jobs/{job_id}/proposals/{proposal_id}/review")
def decide(
    job_id: str,
    proposal_id: str,
    payload: ProposalDecisionInput,
    request: Request,
    identity: Identity,
):
    return request.app.state.evaluations.decide(
        identity, job_id, proposal_id, payload.decision, payload.note
    )
