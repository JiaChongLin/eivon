"""Transactional evaluation batches scored by any worker from durable Run facts."""

from __future__ import annotations

import time
from typing import Any

from jsonschema import Draft202012Validator
from sqlalchemy import func, select, update

from .db import (
    Database,
    EvaluationResult,
    EvaluationReview,
    EvaluationSet,
    ImprovementProposal,
    Job,
    Resource,
    ResourceVersion,
    Run,
    row_dict,
    uid,
)
from .errors import ServiceError
from .resources import Resources, validate_spec
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
                    .where(
                        *self._visible_jobs(principal),
                        Job.input["evaluation_set_id"].as_string() == evaluation_id,
                    )
                    .order_by(Job.created_at.desc(), Job.id)
                    .limit(20)
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
                "results": self._results(db, list(results)),
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
            item = self._job(db, principal, job_id)
            results = db.scalars(
                select(EvaluationResult)
                .where(EvaluationResult.job_id == job_id)
                .order_by(EvaluationResult.case_index)
            )
            return {**row_dict(item), "results": self._results(db, list(results))}

    def _job(self, db, principal, job_id):
        item = db.scalar(select(Job).where(Job.id == job_id, *self._visible_jobs(principal)))
        if item is None:
            raise ServiceError("not_found", "Evaluation job not found", 404)
        return item

    @staticmethod
    def _results(db, rows):
        ids = [row.id for row in rows]
        reviews = {}
        for review in db.scalars(
            select(EvaluationReview)
            .where(EvaluationReview.result_id.in_(ids))
            .order_by(EvaluationReview.created_at, EvaluationReview.id)
        ):
            reviews.setdefault(review.result_id, []).append(row_dict(review))
        return [{**row_dict(row), "reviews": reviews.get(row.id, [])} for row in rows]

    def jobs(self, principal, evaluation_id, offset=0, limit=25):
        principal.require("read")
        with self.database.transaction() as db:
            self._set(db, principal, evaluation_id)
            filters = [
                *self._visible_jobs(principal),
                Job.input["evaluation_set_id"].as_string() == evaluation_id,
            ]
            rows = db.scalars(
                select(Job)
                .where(*filters)
                .order_by(Job.created_at.desc(), Job.id)
                .offset(offset)
                .limit(limit)
            )
            return {
                "items": [
                    {
                        **row_dict(row, ("input",)),
                        "resource_id": row.input["resource_id"],
                        "resource_version": row.input["resource_version"],
                    }
                    for row in rows
                ],
                "total": db.scalar(select(func.count()).select_from(Job).where(*filters)),
            }

    def compare(self, principal, baseline_id, candidate_id):
        principal.require("read")
        baseline, candidate = self.job(principal, baseline_id), self.job(principal, candidate_id)
        if any(job["status"] not in {"completed", "timed_out"} for job in [baseline, candidate]):
            raise ServiceError("not_complete", "Wait for both evaluation batches to finish", 409)
        for key in ["evaluation_set_id", "evaluation_revision", "resource_id", "cases"]:
            if baseline["input"][key] != candidate["input"][key]:
                raise ServiceError(
                    "incompatible_jobs", "Compare the same Agent and identical test cases", 422
                )
        rows = []
        right = {row["case_index"]: row for row in candidate["results"]}
        for left in baseline["results"]:
            item = right[left["case_index"]]
            delta = item["score"] - left["score"]
            rows.append(
                {
                    "case_index": left["case_index"],
                    "baseline": left,
                    "candidate": item,
                    "delta": delta,
                    "change": "improved"
                    if delta > 0
                    else "regressed"
                    if delta < 0
                    else "unchanged",
                }
            )
        return {
            "baseline": baseline,
            "candidate": candidate,
            "score_delta": candidate["output"]["score"] - baseline["output"]["score"],
            "improved": sum(row["change"] == "improved" for row in rows),
            "regressed": sum(row["change"] == "regressed" for row in rows),
            "cases": rows,
        }

    def review_result(self, principal, job_id, result_id, score, note):
        principal.require("write")
        with self.database.transaction() as db:
            self._job(db, principal, job_id)
            result = db.get(EvaluationResult, result_id)
            if result is None or result.job_id != job_id:
                raise ServiceError("not_found", "Evaluation result not found", 404)
            review = EvaluationReview(
                result_id=result_id, user_id=principal.user_id, score=score, note=note
            )
            db.add(review)
            db.flush()
            audit(db, principal, "evaluation.review", result_id, review_id=review.id, score=score)
            return row_dict(review)

    def reflection(self, principal, job_id):
        job = self.job(principal, job_id)
        if job["status"] not in {"completed", "timed_out"}:
            raise ServiceError("not_complete", "Wait for evaluation results before reflecting", 409)
        failures = [
            {
                "case_index": row["case_index"],
                "run_id": row["run_id"],
                "status": row["status"],
                "input": row["input"],
                "expected": row["expected"],
                "actual": row["actual"],
            }
            for row in job["results"]
            if row["score"] < 1
        ]
        with self.database.transaction() as db:
            run = db.get(Run, job["input"]["run_ids"][0])
            targets = []
            for value in run.snapshot["resources"].values():
                if value["kind"] in {"prompt", "skill"}:
                    resource = self.runs.resources._get(db, principal, value["id"])
                    targets.append(
                        {
                            "id": resource.id,
                            "name": resource.name,
                            "kind": resource.kind,
                            "version": value["version"],
                            "revision": resource.revision,
                            "draft": resource.draft,
                            "archived": resource.archived,
                        }
                    )
            proposals = db.scalars(
                select(ImprovementProposal)
                .where(ImprovementProposal.job_id == job_id)
                .order_by(ImprovementProposal.created_at.desc(), ImprovementProposal.id)
            )
            return {
                "job_id": job_id,
                "failures": failures,
                "targets": targets,
                "proposals": [row_dict(row) for row in proposals],
                "summary": f"{len(failures)} of {len(job['results'])} cases failed the configured checks. Review the evidence before proposing instruction changes.",
            }

    def propose(self, principal, job_id, resource_id, revision, text, rationale):
        principal.require("write")
        with self.database.transaction() as db:
            job = self._job(db, principal, job_id)
            if job.status not in {"completed", "timed_out"}:
                raise ServiceError(
                    "not_complete", "Wait for evaluation results before proposing", 409
                )
            run = db.get(Run, job.input["run_ids"][0])
            targets = {
                r["id"]
                for r in run.snapshot["resources"].values()
                if r["kind"] in {"prompt", "skill"}
            }
            if resource_id not in targets:
                raise ServiceError(
                    "invalid_target", "Choose a Prompt or Skill from this evaluated release", 422
                )
            resource = Resources._get(db, principal, resource_id)
            if resource.archived or resource.revision != revision:
                raise ServiceError(
                    "revision_conflict", "The target changed. Reload before proposing", 409
                )
            field = "template" if resource.kind == "prompt" else "body"
            candidate = validate_spec(resource.kind, {**resource.draft, field: text})
            if candidate == resource.draft:
                raise ServiceError(
                    "no_change", "The proposed instructions must differ from the draft", 422
                )
            item = ImprovementProposal(
                workspace_id=principal.workspace_id,
                job_id=job_id,
                user_id=principal.user_id,
                resource_id=resource_id,
                base_revision=revision,
                base_spec=resource.draft,
                candidate_spec=candidate,
                rationale=rationale,
            )
            db.add(item)
            db.flush()
            audit(
                db,
                principal,
                "improvement.propose",
                item.id,
                job_id=job_id,
                resource_id=resource_id,
            )
            return row_dict(item)

    def decide(self, principal, job_id, proposal_id, decision, note):
        principal.require("admin")
        if decision == "accepted":
            principal.require("write")
        with self.database.transaction() as db:
            self._job(db, principal, job_id)
            item = db.scalar(
                select(ImprovementProposal).where(
                    ImprovementProposal.id == proposal_id,
                    ImprovementProposal.job_id == job_id,
                    ImprovementProposal.workspace_id == principal.workspace_id,
                )
            )
            if item is None:
                raise ServiceError("not_found", "Improvement proposal not found", 404)
            changed = db.execute(
                update(ImprovementProposal)
                .where(ImprovementProposal.id == item.id, ImprovementProposal.status == "pending")
                .values(
                    status=decision,
                    reviewer_id=principal.user_id,
                    reviewed_at=time.time(),
                    review_note=note,
                )
            )
            if changed.rowcount != 1:
                raise ServiceError(
                    "already_reviewed", "This proposal has already been reviewed", 409
                )
            if decision == "accepted":
                resource = Resources._get(db, principal, item.resource_id)
                candidate = validate_spec(resource.kind, item.candidate_spec)
                self.runs.resources._snapshot(db, principal, resource, candidate)
                updated = db.execute(
                    update(Resource)
                    .where(
                        Resource.id == resource.id,
                        Resource.revision == item.base_revision,
                        Resource.archived.is_(False),
                    )
                    .values(
                        draft=candidate, revision=item.base_revision + 1, updated_at=time.time()
                    )
                )
                if updated.rowcount != 1:
                    raise ServiceError(
                        "revision_conflict",
                        "The draft changed after this proposal. Reject it and propose against the new revision",
                        409,
                    )
                item.applied_revision = item.base_revision + 1
            audit(db, principal, f"improvement.{decision}", item.id, resource_id=item.resource_id)
            db.flush()
            db.refresh(item)
            return row_dict(item)
