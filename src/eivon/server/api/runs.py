"""Conversation and run APIs with resumable ordered events."""

from __future__ import annotations

import asyncio
import json
from typing import AsyncIterator

from fastapi import APIRouter, Query, Request
from fastapi.responses import StreamingResponse
from pydantic import Field

from eivon.core.contracts import Contract

from .dependencies import Identity

router = APIRouter()


class SessionInput(Contract):
    agent_id: str
    title: str = Field(default="New conversation", max_length=200)
    context: dict = Field(default_factory=dict)


class RunInput(Contract):
    resource_id: str
    message: str = Field(default="", max_length=60_000)
    context: dict = Field(default_factory=dict)
    input: dict | None = None
    version: int | None = None
    session_id: str | None = None
    idempotency_key: str | None = Field(default=None, max_length=100)
    draft: bool = False


class ResumeInput(Contract):
    response: dict = Field(default_factory=dict)
    expected_sequence: int = Field(ge=0)


@router.get("/sessions")
def sessions(
    request: Request,
    identity: Identity,
    offset: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=200),
):
    return request.app.state.runs.sessions(identity, offset, limit)


@router.post("/sessions", status_code=201)
def create_session(payload: SessionInput, request: Request, identity: Identity):
    return request.app.state.runs.create_session(identity, **payload.model_dump())


@router.get("/sessions/{session_id}")
def session(session_id: str, request: Request, identity: Identity):
    return request.app.state.runs.session(identity, session_id)


@router.get("/runs")
def list_runs(
    request: Request,
    identity: Identity,
    offset: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=200),
    status: str | None = None,
):
    return request.app.state.runs.list(identity, offset, limit, status)


@router.post("/runs", status_code=202)
def create_run(payload: RunInput, request: Request, identity: Identity):
    values = payload.model_dump()
    message = values.pop("message")
    context = values.pop("context")
    workflow_input = values.pop("input")
    values["payload"] = {"message": message, "context": context}
    if workflow_input is not None:
        values["payload"]["input"] = workflow_input
    return request.app.state.runs.create(identity, **values)


@router.get("/runs/{run_id}")
def run(run_id: str, request: Request, identity: Identity):
    return request.app.state.runs.get(identity, run_id)


@router.get("/runs/{run_id}/events")
def events(
    run_id: str,
    request: Request,
    identity: Identity,
    after: int = Query(0, ge=0),
    limit: int = Query(200, ge=1, le=500),
):
    return {"items": request.app.state.runs.events(identity, run_id, after, limit)}


@router.get("/runs/{run_id}/events/stream")
async def event_stream(
    run_id: str, request: Request, identity: Identity, after: int = Query(0, ge=0)
):
    async def stream() -> AsyncIterator[str]:
        sequence = after
        idle = 0
        while idle < 600:
            if await request.is_disconnected():
                return
            rows = request.app.state.runs.events(identity, run_id, sequence, 200)
            if rows:
                idle = 0
                for item in rows:
                    sequence = item["sequence"]
                    yield (
                        "id: "
                        + str(sequence)
                        + "\ndata: "
                        + json.dumps(item, ensure_ascii=False)
                        + "\n\n"
                    )
                current = request.app.state.runs.get(identity, run_id)
                if current["status"] in {"completed", "failed", "cancelled"}:
                    return
            else:
                idle += 1
                await asyncio.sleep(0.5)

    return StreamingResponse(
        stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@router.post("/runs/{run_id}/cancel")
def cancel(run_id: str, request: Request, identity: Identity):
    return request.app.state.runs.cancel(identity, run_id)


@router.post("/runs/{run_id}/resume")
def resume(run_id: str, payload: ResumeInput, request: Request, identity: Identity):
    return request.app.state.runs.resume(
        identity, run_id, payload.response, payload.expected_sequence
    )
