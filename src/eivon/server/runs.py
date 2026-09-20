"""Durable execution state, atomic event order and worker fencing."""

from __future__ import annotations

import time

from jsonschema import Draft202012Validator
from sqlalchemy import func, select, update
from sqlalchemy.exc import IntegrityError

from eivon.core.contracts import ModelMessage

from .db import Database, Member, ResourceVersion, Run, RunEvent, Session, row_dict, uid
from .errors import ServiceError
from .resources import Resources
from .security import ROLE_PERMISSIONS, Principal, audit

TERMINAL = frozenset({"completed", "failed", "cancelled"})
WAITING = frozenset({"waiting_input", "waiting_approval"})


class LeaseLost(RuntimeError):
    pass


class Runs:
    def __init__(self, database: Database, resources: Resources):
        self.database, self.resources = database, resources

    @staticmethod
    def _access(item, principal: Principal):
        if item is None or item.workspace_id != principal.workspace_id:
            raise ServiceError("not_found", "Execution resource not found", 404)
        if item.user_id != principal.user_id and "admin" not in principal.permissions:
            raise ServiceError("not_found", "Execution resource not found", 404)
        return item

    def create_session(
        self, principal: Principal, agent_id: str, title: str, context: dict
    ) -> dict:
        principal.require("execute")
        with self.database.transaction() as db:
            agent = Resources._get(db, principal, agent_id)
            if agent.kind != "agent" or agent.archived:
                raise ServiceError("invalid_agent", "Choose an active Agent")
            item = Session(
                workspace_id=principal.workspace_id,
                user_id=principal.user_id,
                agent_id=agent_id,
                title=title,
                context=context,
            )
            db.add(item)
            db.flush()
            return row_dict(item)

    def sessions(self, principal: Principal, offset: int, limit: int) -> dict:
        principal.require("read")
        with self.database.transaction() as db:
            filters = [
                Session.workspace_id == principal.workspace_id,
                Session.user_id == principal.user_id,
            ]
            items = db.scalars(
                select(Session)
                .where(*filters)
                .order_by(Session.updated_at.desc(), Session.id)
                .offset(offset)
                .limit(limit)
            )
            return {
                "items": [row_dict(s) for s in items],
                "total": db.scalar(select(func.count()).select_from(Session).where(*filters)),
            }

    def session(self, principal: Principal, session_id: str) -> dict:
        principal.require("read")
        with self.database.transaction() as db:
            session = self._access(db.get(Session, session_id), principal)
            runs = db.scalars(
                select(Run).where(Run.session_id == session_id).order_by(Run.created_at, Run.id)
            )
            return {
                **row_dict(session),
                "runs": [row_dict(r, ("snapshot", "checkpoint")) for r in runs],
            }

    def create(
        self,
        principal: Principal,
        resource_id: str,
        payload: dict,
        version: int | None = None,
        session_id: str | None = None,
        idempotency_key: str | None = None,
        draft: bool = False,
    ) -> dict:
        principal.require("execute")
        if draft:
            principal.require("write")
        try:
            with self.database.transaction() as db:
                if idempotency_key:
                    previous = db.scalar(
                        select(Run).where(
                            Run.workspace_id == principal.workspace_id,
                            Run.user_id == principal.user_id,
                            Run.idempotency_key == idempotency_key,
                        )
                    )
                    if previous:
                        if (
                            previous.resource_id != resource_id
                            or previous.input != payload
                            or previous.session_id != session_id
                        ):
                            raise ServiceError(
                                "idempotency_conflict",
                                "This idempotency key was used for a different request",
                                409,
                            )
                        return row_dict(previous, ("snapshot", "checkpoint"))
                resource = Resources._get(db, principal, resource_id)
                if resource.archived or resource.kind not in {"agent", "workflow", "tool"}:
                    raise ServiceError("not_executable", "Choose an active Agent, Workflow or Tool")
                selected_version = version or resource.active_version
                if draft:
                    snapshot = self.resources._snapshot(db, principal, resource, resource.draft)
                    snapshot["draft_revision"] = resource.revision
                    selected_version = 0
                else:
                    release = (
                        db.get(ResourceVersion, (resource_id, selected_version))
                        if selected_version
                        else None
                    )
                    if release is None:
                        raise ServiceError(
                            "not_published", "Publish this resource before running it", 409
                        )
                    snapshot = release.snapshot
                session = None
                if session_id:
                    session = self._access(db.get(Session, session_id), principal)
                    if resource.kind != "agent" or session.agent_id != resource_id:
                        raise ServiceError(
                            "session_agent_mismatch", "Session belongs to a different Agent", 409
                        )
                    context = session.context
                else:
                    context = payload.get("context", {})
                root_spec = snapshot["root"]["spec"]
                if resource.kind == "agent":
                    schemas = [root_spec["context_schema"]] + [
                        r["spec"]["context_schema"]
                        for r in snapshot["resources"].values()
                        if r["kind"] == "bundle"
                    ]
                    for schema in schemas:
                        if not Draft202012Validator(schema).is_valid(context):
                            raise ServiceError(
                                "invalid_context",
                                "Business context does not match the configured schema",
                                422,
                            )
                run_id = uid()
                if session:
                    claimed = db.execute(
                        update(Session)
                        .where(Session.id == session.id, Session.active_run_id.is_(None))
                        .values(active_run_id=run_id, updated_at=time.time())
                    )
                    if claimed.rowcount != 1:
                        raise ServiceError(
                            "session_busy", "This session has an active or waiting run", 409
                        )
                item = Run(
                    id=run_id,
                    workspace_id=principal.workspace_id,
                    user_id=principal.user_id,
                    session_id=session_id,
                    resource_id=resource.id,
                    resource_version=selected_version,
                    kind=resource.kind,
                    snapshot=snapshot,
                    input=payload,
                    idempotency_key=idempotency_key,
                )
                db.add(item)
                db.flush()
                self._event(
                    db, item, "run.queued", {"kind": resource.kind, "version": selected_version}
                )
                audit(
                    db,
                    principal,
                    "run.create",
                    run_id,
                    resource_id=resource_id,
                    version=selected_version,
                )
                return row_dict(item, ("snapshot", "checkpoint"))
        except IntegrityError as exc:
            if idempotency_key:
                with self.database.transaction() as db:
                    previous = db.scalar(
                        select(Run).where(
                            Run.workspace_id == principal.workspace_id,
                            Run.user_id == principal.user_id,
                            Run.idempotency_key == idempotency_key,
                        )
                    )
                    if (
                        previous
                        and previous.resource_id == resource_id
                        and previous.input == payload
                        and previous.session_id == session_id
                    ):
                        return row_dict(previous, ("snapshot", "checkpoint"))
            raise ServiceError(
                "run_conflict", "Run creation conflicted with another request", 409
            ) from exc

    def list(
        self, principal: Principal, offset: int, limit: int, status: str | None = None
    ) -> dict:
        principal.require("read")
        filters = [Run.workspace_id == principal.workspace_id]
        if "admin" not in principal.permissions:
            filters.append(Run.user_id == principal.user_id)
        if status:
            filters.append(Run.status == status)
        with self.database.transaction() as db:
            rows = db.scalars(
                select(Run)
                .where(*filters)
                .order_by(Run.created_at.desc(), Run.id)
                .offset(offset)
                .limit(limit)
            )
            return {
                "items": [row_dict(r, ("snapshot", "checkpoint")) for r in rows],
                "total": db.scalar(select(func.count()).select_from(Run).where(*filters)),
            }

    def get(self, principal: Principal, run_id: str) -> dict:
        principal.require("read")
        with self.database.transaction() as db:
            run = self._access(db.get(Run, run_id), principal)
            return row_dict(run)

    def events(self, principal: Principal, run_id: str, after: int, limit: int = 200) -> list[dict]:
        principal.require("read")
        with self.database.transaction() as db:
            self._access(db.get(Run, run_id), principal)
            return [
                row_dict(e)
                for e in db.scalars(
                    select(RunEvent)
                    .where(RunEvent.run_id == run_id, RunEvent.sequence > after)
                    .order_by(RunEvent.sequence)
                    .limit(limit)
                )
            ]

    @staticmethod
    def _event(db, run: Run, kind: str, data: dict):
        sequence = db.scalar(
            update(Run)
            .where(Run.id == run.id)
            .values(event_sequence=Run.event_sequence + 1)
            .returning(Run.event_sequence)
        )
        db.add(RunEvent(run_id=run.id, sequence=sequence, type=kind, data=data))

    def cancel(self, principal: Principal, run_id: str) -> dict:
        principal.require("execute")
        with self.database.transaction() as db:
            run = self._access(
                db.scalar(select(Run).where(Run.id == run_id).with_for_update()), principal
            )
            if run.status in TERMINAL:
                return row_dict(run, ("snapshot", "checkpoint"))
            run.cancel_requested = True
            if run.status in WAITING or run.status == "queued":
                run.status, run.finished_at = "cancelled", time.time()
                self._release_session(db, run)
                self._event(db, run, "run.cancelled", {})
            else:
                run.status = "cancelling"
                self._event(db, run, "run.cancel_requested", {})
            audit(db, principal, "run.cancel", run_id)
            db.flush()
            return row_dict(run, ("snapshot", "checkpoint"))

    def resume(
        self, principal: Principal, run_id: str, response: dict, expected_sequence: int
    ) -> dict:
        principal.require("execute")
        with self.database.transaction() as db:
            run = self._access(
                db.scalar(select(Run).where(Run.id == run_id).with_for_update()), principal
            )
            if run.status not in WAITING or run.event_sequence != expected_sequence:
                raise ServiceError(
                    "resume_conflict", "This run is no longer waiting for this response", 409
                )
            if run.status == "waiting_approval":
                principal.require("approve")
                if not isinstance(response.get("approved"), bool):
                    raise ServiceError(
                        "invalid_response", "Approval requires an explicit approved boolean"
                    )
            else:
                schema = run.checkpoint.get("waiting", {}).get("input_schema", {"type": "object"})
                if not Draft202012Validator(schema).is_valid(response):
                    raise ServiceError(
                        "invalid_response", "Response does not match the input schema", 422
                    )
            checkpoint = {
                **run.checkpoint,
                "resume_response": response,
                "resumed_by": principal.user_id,
            }
            changed = db.execute(
                update(Run)
                .where(
                    Run.id == run.id,
                    Run.status == run.status,
                    Run.event_sequence == expected_sequence,
                )
                .values(status="queued", checkpoint=checkpoint, worker_id=None, lease_until=None)
            )
            if changed.rowcount != 1:
                raise ServiceError(
                    "resume_conflict", "This response has already been submitted", 409
                )
            db.refresh(run)
            self._event(db, run, "run.resumed", {"actor_id": principal.user_id})
            audit(db, principal, "run.resume", run_id)
            return row_dict(run, ("snapshot", "checkpoint"))

    def claim(self, worker_id: str, lease_seconds: int) -> dict | None:
        with self.database.transaction() as db:
            # An abandoned execution has uncertain side effects. Never silently replay it.
            stale = list(
                db.scalars(
                    select(Run)
                    .where(Run.status.in_(["running", "cancelling"]), Run.lease_until < time.time())
                    .with_for_update(skip_locked=True)
                )
            )
            for run in stale:
                run.status = "cancelled" if run.cancel_requested else "failed"
                run.error = "Worker lease expired. External side effects may have completed; inspect before rerunning."
                run.finished_at = time.time()
                run.worker_id = None
                self._release_session(db, run)
                self._event(db, run, "run." + run.status, {"error": run.error})
            db.flush()
            candidate = db.scalar(
                select(Run)
                .where(Run.status == "queued")
                .order_by(Run.created_at, Run.id)
                .with_for_update(skip_locked=True)
                .limit(1)
            )
            if candidate is None:
                return None
            changed = db.execute(
                update(Run)
                .where(Run.id == candidate.id, Run.status == "queued")
                .values(
                    status="running",
                    worker_id=worker_id,
                    lease_until=time.time() + lease_seconds,
                    started_at=candidate.started_at or time.time(),
                )
            )
            if changed.rowcount != 1:
                return None
            db.refresh(candidate)
            membership = db.get(Member, (candidate.workspace_id, candidate.user_id))
            if not membership or "execute" not in ROLE_PERMISSIONS[membership.role]:
                candidate.status, candidate.error, candidate.finished_at = (
                    "failed",
                    "Run owner no longer has execution access",
                    time.time(),
                )
                self._release_session(db, candidate)
                self._event(db, candidate, "run.failed", {"error": candidate.error})
                return None
            self._event(db, candidate, "run.started", {"worker_id": worker_id})
            result = row_dict(candidate)
            if candidate.session_id:
                session = db.get(Session, candidate.session_id)
                result["business_context"] = session.context
                history = list(
                    db.scalars(
                        select(Run)
                        .where(
                            Run.session_id == candidate.session_id,
                            Run.status == "completed",
                            Run.id != candidate.id,
                        )
                        .order_by(Run.created_at.desc())
                        .limit(10)
                    )
                )
                messages = []
                for previous in reversed(history):
                    messages += [
                        ModelMessage(
                            role="user", content=str(previous.input.get("message", ""))
                        ).model_dump(),
                        ModelMessage(
                            role="assistant", content=str(previous.output.get("text", ""))
                        ).model_dump(),
                    ]
                result["history"] = messages
            else:
                result["business_context"] = candidate.input.get("context", {})
                result["history"] = []
            return result

    def heartbeat(self, run_id: str, worker_id: str, lease_seconds: int) -> bool:
        with self.database.transaction() as db:
            return (
                db.execute(
                    update(Run)
                    .where(
                        Run.id == run_id,
                        Run.worker_id == worker_id,
                        Run.status.in_(["running", "cancelling"]),
                        Run.lease_until > time.time(),
                    )
                    .values(lease_until=time.time() + lease_seconds)
                ).rowcount
                == 1
            )

    def _owned(self, db, run_id: str, worker_id: str):
        run = db.scalar(
            select(Run)
            .where(
                Run.id == run_id,
                Run.worker_id == worker_id,
                Run.status.in_(["running", "cancelling"]),
                Run.lease_until > time.time(),
            )
            .with_for_update()
        )
        if run is None:
            raise LeaseLost("Worker no longer owns this run")
        return run

    def emit(self, run_id: str, worker_id: str, kind: str, data: dict) -> None:
        with self.database.transaction() as db:
            run = self._owned(db, run_id, worker_id)
            self._event(db, run, kind, data)

    def save_checkpoint(
        self, run_id: str, worker_id: str, checkpoint: dict, usage: dict | None = None
    ) -> None:
        with self.database.transaction() as db:
            run = self._owned(db, run_id, worker_id)
            run.checkpoint = checkpoint
            if usage is not None:
                run.usage = usage

    def cancelled(self, run_id: str, worker_id: str) -> bool:
        with self.database.transaction() as db:
            run = self._owned(db, run_id, worker_id)
            member = db.get(Member, (run.workspace_id, run.user_id))
            return (
                run.cancel_requested
                or member is None
                or "execute" not in ROLE_PERMISSIONS[member.role]
            )

    def finish(
        self,
        run_id: str,
        worker_id: str,
        status: str,
        *,
        output: dict | None = None,
        error: str | None = None,
        checkpoint: dict | None = None,
    ):
        if status not in TERMINAL | WAITING:
            raise ValueError("Invalid final or waiting status")
        with self.database.transaction() as db:
            run = self._owned(db, run_id, worker_id)
            if run.cancel_requested:
                status = "cancelled"
            run.status, run.output, run.error = status, output or {}, error
            run.worker_id, run.lease_until = None, None
            if checkpoint is not None:
                run.checkpoint = checkpoint
            if status in TERMINAL:
                run.finished_at = time.time()
                self._release_session(db, run)
            self._event(
                db,
                run,
                "run." + status,
                {
                    "output": run.output,
                    "error": error,
                    "waiting": run.checkpoint.get("waiting") if status in WAITING else None,
                },
            )

    @staticmethod
    def _release_session(db, run: Run):
        if run.session_id:
            db.execute(
                update(Session)
                .where(Session.id == run.session_id, Session.active_run_id == run.id)
                .values(active_run_id=None, updated_at=time.time())
            )
