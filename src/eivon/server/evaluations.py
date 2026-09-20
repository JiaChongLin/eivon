"""Transactional evaluation batches scored by any worker from durable Run facts."""

from __future__ import annotations

import time
from typing import Any

from jsonschema import Draft202012Validator
from sqlalchemy import func, select, update

from .db import Database, EvaluationResult, EvaluationSet, Job, ResourceVersion, Run, row_dict, uid
from .errors import ServiceError
from .resources import Resources
from .runs import TERMINAL, WAITING, Runs
from .security import Principal, audit


def _validate_cases(cases: list[dict[str, Any]]) -> list[dict[str, Any]]:
    if not 1 <= len(cases) <= 500:
        raise ServiceError("invalid_cases", "An evaluation set requires 1 to 500 cases", 422)
    clean = []
    for index, case in enumerate(cases):
        message, expected = case.get("input"), case.get("expected", "")
        matcher, context = case.get("match", "contains"), case.get("context", {})
        if not isinstance(message, str) or not 1 <= len(message) <= 60_000:
            raise ServiceError("invalid_case", f"Case {index} requires a bounded input string", 422)
        if not isinstance(expected, str) or len(expected) > 60_000:
            raise ServiceError(
                "invalid_case", f"Case {index} requires a bounded expected string", 422
            )
        if matcher not in {"contains", "exact", "nonempty"} or not isinstance(context, dict):
            raise ServiceError("invalid_case", f"Case {index} has invalid match or context", 422)
        if matcher == "contains" and not expected.strip():
            raise ServiceError(
                "invalid_case", "Contains scoring requires nonempty expected text", 422
            )
        clean.append({"input": message, "expected": expected, "match": matcher, "context": context})
    return clean


def score_case(case: dict[str, Any], actual: str) -> float:
    expected, matcher = case.get("expected", ""), case.get("match", "contains")
    if matcher == "nonempty":
        return float(bool(actual.strip()))
    if matcher == "exact":
        return float(actual.strip() == expected.strip())
    return float(bool(expected.strip()) and expected.casefold() in actual.casefold())


class Evaluations:
    def __init__(self, database: Database, runs: Runs):
        self.database, self.runs = database, runs

    @staticmethod
    def _set(db, principal, evaluation_id):
        item = db.get(EvaluationSet, evaluation_id)
        if item is None or item.workspace_id != principal.workspace_id:
            raise ServiceError("not_found", "Evaluation set not found", 404)
        return item

    @staticmethod
    def _visible_jobs(principal):
        filters = [Job.workspace_id == principal.workspace_id, Job.kind == "evaluation"]
        if "admin" not in principal.permissions:
            filters.append(Job.user_id == principal.user_id)
        return filters

    def create(self, principal: Principal, name: str, cases: list[dict[str, Any]]) -> dict:
        principal.require("write")
        clean = _validate_cases(cases)
        with self.database.transaction() as db:
            item = EvaluationSet(workspace_id=principal.workspace_id, name=name, cases=clean)
            db.add(item)
            db.flush()
            audit(db, principal, "evaluation.create", item.id, case_count=len(clean))
            return row_dict(item)

    def list(self, principal: Principal, offset=0, limit=50) -> dict:
        principal.require("read")
        with self.database.transaction() as db:
            filters = [EvaluationSet.workspace_id == principal.workspace_id]
            rows = db.scalars(
                select(EvaluationSet)
                .where(*filters)
                .order_by(EvaluationSet.created_at.desc(), EvaluationSet.id)
                .offset(offset)
                .limit(limit)
            )
            return {
                "items": [row_dict(item, ("cases",)) for item in rows],
                "total": db.scalar(select(func.count()).select_from(EvaluationSet).where(*filters)),
            }

    def get(self, principal: Principal, evaluation_id: str) -> dict:
        principal.require("read")
        with self.database.transaction() as db:
            item = self._set(db, principal, evaluation_id)
            jobs = [
                job
                for job in db.scalars(
                    select(Job)
                    .where(*self._visible_jobs(principal))
                    .order_by(Job.created_at.desc(), Job.id)
                    .limit(100)
                )
                if job.input.get("evaluation_set_id") == evaluation_id
            ][:20]
            results = db.scalars(
                select(EvaluationResult)
                .where(EvaluationResult.job_id == jobs[0].id if jobs else False)
                .order_by(EvaluationResult.case_index)
            )
            return {
                **row_dict(item),
                "results": [row_dict(r) for r in results],
                "jobs": [row_dict(job, ("input",)) for job in jobs],
            }

    def start(
        self,
        principal: Principal,
        evaluation_id: str,
        resource_id: str,
        version: int | None,
        timeout_seconds: int,
    ) -> dict:
        principal.require("execute")
        with self.database.transaction() as db:
            evaluation = self._set(db, principal, evaluation_id)
            resource = Resources._get(db, principal, resource_id)
            if resource.kind != "agent" or resource.archived:
                raise ServiceError(
                    "invalid_agent", "Evaluations require an active published Agent", 422
                )
            selected = version if version is not None else resource.active_version
            release = db.get(ResourceVersion, (resource_id, selected)) if selected else None
            if release is None:
                raise ServiceError("not_published", "Agent version is not published", 409)
            snapshot = release.snapshot
            schemas = [snapshot["root"]["spec"]["context_schema"]] + [
                r["spec"]["context_schema"]
                for r in snapshot["resources"].values()
                if r["kind"] == "bundle"
            ]
            cases = _validate_cases(evaluation.cases)
            for case in cases:
                if any(not Draft202012Validator(s).is_valid(case["context"]) for s in schemas):
                    raise ServiceError(
                        "invalid_context", "Evaluation case context does not match the Agent", 422
                    )
            job_id = uid()
            run_ids = []
            for index, case in enumerate(cases):
                run = Run(
                    workspace_id=principal.workspace_id,
                    user_id=principal.user_id,
                    resource_id=resource_id,
                    resource_version=selected,
                    kind="agent",
                    snapshot=snapshot,
                    input={"message": case["input"], "context": case["context"]},
                    idempotency_key=f"eval:{job_id}:{index}",
                )
                db.add(run)
                db.flush()
                self.runs._event(
                    db,
                    run,
                    "run.queued",
                    {"kind": "agent", "version": selected, "evaluation_job": job_id},
                )
                run_ids.append(run.id)
            job = Job(
                id=job_id,
                workspace_id=principal.workspace_id,
                user_id=principal.user_id,
                kind="evaluation",
                status="running",
                input={
                    "evaluation_set_id": evaluation_id,
                    "evaluation_revision": evaluation.revision,
                    "resource_id": resource_id,
                    "resource_version": selected,
                    "cases": cases,
                    "run_ids": run_ids,
                    "deadline": time.time() + timeout_seconds,
                },
            )
            db.add(job)
            db.flush()
            audit(db, principal, "evaluation.start", job.id, evaluation_set_id=evaluation_id)
            return row_dict(job)

    def reconcile(self) -> int:
        """Atomically finalize ready batches; restarting a worker needs no in-memory tasks."""
        with self.database.transaction() as db:
            ids = list(
                db.scalars(select(Job.id).where(Job.kind == "evaluation", Job.status == "running"))
            )
        completed = 0
        for job_id in ids:
            with self.database.transaction() as db:
                # Acquire the write lock before reading Run state. The status compare-and-set
                # prevents concurrent workers from scoring a batch twice on both databases.
                claimed = db.execute(
                    update(Job)
                    .where(Job.id == job_id, Job.status == "running")
                    .values(status="scoring")
                )
                if claimed.rowcount != 1:
                    continue
                job = db.get(Job, job_id)
                runs = [db.get(Run, run_id) for run_id in job.input["run_ids"]]
                expired = time.time() >= job.input["deadline"]
                if not expired and any(run.status not in TERMINAL for run in runs):
                    job.status = "running"
                    continue
                scores = []
                timed_out = False
                for index, (case, run) in enumerate(zip(job.input["cases"], runs, strict=True)):
                    status = run.status
                    actual = str(run.output.get("text", ""))
                    score = score_case(case, actual) if status == "completed" else 0.0
                    if status not in TERMINAL:
                        timed_out = True
                        run.cancel_requested = True
                        if status in WAITING or status == "queued":
                            run.status, run.finished_at = "cancelled", time.time()
                            self.runs._event(
                                db, run, "run.cancelled", {"reason": "evaluation_timeout"}
                            )
                        else:
                            run.status = "cancelling"
                            self.runs._event(
                                db, run, "run.cancel_requested", {"reason": "evaluation_timeout"}
                            )
                        status = "timed_out"
                    elif status == "completed":
                        status = "passed" if score == 1.0 else "failed"
                    scores.append(score)
                    db.add(
                        EvaluationResult(
                            job_id=job.id,
                            evaluation_set_id=job.input["evaluation_set_id"],
                            workspace_id=job.workspace_id,
                            resource_id=run.resource_id,
                            resource_version=run.resource_version,
                            case_index=index,
                            run_id=run.id,
                            input=case,
                            expected=case["expected"],
                            actual=actual,
                            score=score,
                            status=status,
                        )
                    )
                job.status = "timed_out" if timed_out else "completed"
                job.output = {
                    "count": len(scores),
                    "passed": scores.count(1.0),
                    "score": sum(scores) / len(scores),
                    "resource_version": job.input["resource_version"],
                }
                job.finished_at = time.time()
                completed += 1
        return completed

    def job(self, principal: Principal, job_id: str) -> dict:
        principal.require("read")
        with self.database.transaction() as db:
            item = db.scalar(select(Job).where(Job.id == job_id, *self._visible_jobs(principal)))
            if item is None:
                raise ServiceError("not_found", "Evaluation job not found", 404)
            results = db.scalars(
                select(EvaluationResult)
                .where(EvaluationResult.job_id == job_id)
                .order_by(EvaluationResult.case_index)
            )
            return {**row_dict(item), "results": [row_dict(r) for r in results]}
