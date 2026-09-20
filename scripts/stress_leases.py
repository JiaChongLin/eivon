"""Measure concurrent run claiming and lease fencing on a local Eivon database."""

from __future__ import annotations

import argparse
import json
import tempfile
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

from sqlalchemy import func, select

from eivon.server.db import Database, Member, Resource, Run, User, Workspace, uid
from eivon.server.resources import Resources
from eivon.server.runs import LeaseLost, Runs
from eivon.server.settings import Settings


def _seed(settings: Settings, count: int) -> tuple[str, str]:
    database = Database(settings)
    database.initialize()
    workspace_id, user_id, resource_id = uid(), uid(), uid()
    with database.transaction() as db:
        db.add(
            User(
                id=user_id,
                email="stress-owner@example.test",
                name="Stress owner",
                password_hash="unused",
            )
        )
        db.add(Workspace(id=workspace_id, name="Stress workspace"))
        db.flush()
        db.add(Member(workspace_id=workspace_id, user_id=user_id, role="owner"))
        db.add(
            Resource(
                id=resource_id,
                workspace_id=workspace_id,
                kind="agent",
                slug="stress-agent",
                name="Stress agent",
                draft={},
            )
        )
        db.flush()
        for index in range(count):
            db.add(
                Run(
                    id=uid(),
                    workspace_id=workspace_id,
                    user_id=user_id,
                    resource_id=resource_id,
                    resource_version=0,
                    kind="agent",
                    status="queued",
                    snapshot={},
                    input={"message": f"stress-{index}"},
                    created_at=time.time() + index / count / 1000,
                )
            )
    database.engine.dispose()
    return workspace_id, user_id


def _claim_worker(settings: Settings, worker_id: str) -> tuple[list[str], list[str]]:
    database = Database(settings)
    runs = Runs(database, Resources(database))
    claimed: list[str] = []
    errors: list[str] = []
    try:
        while True:
            try:
                item = runs.claim(worker_id, settings.lease_seconds)
            except Exception as exc:  # pragma: no cover - surfaced in the JSON report
                errors.append(f"{type(exc).__name__}: {exc}")
                break
            if item is None:
                break
            claimed.append(item["id"])
    finally:
        database.engine.dispose()
    return claimed, errors


def run_stress(data_dir: Path, count: int = 128, workers: int = 8) -> dict:
    """Run a deterministic local stress scenario and return a machine-readable report."""
    if count < 1 or workers < 1:
        raise ValueError("count and workers must be positive")
    settings = Settings(data_dir=data_dir, inline_worker=False, lease_seconds=30)
    _seed(settings, count)
    started = time.perf_counter()
    claimed: list[str] = []
    errors: list[str] = []
    with ThreadPoolExecutor(max_workers=workers, thread_name_prefix="eivon-stress") as pool:
        futures = [pool.submit(_claim_worker, settings, f"stress-{index}") for index in range(workers)]
        for future in as_completed(futures):
            worker_claims, worker_errors = future.result()
            claimed.extend(worker_claims)
            errors.extend(worker_errors)
    elapsed = time.perf_counter() - started
    unique_claims = set(claimed)

    database = Database(settings)
    with database.transaction() as db:
        statuses = {
            status: total
            for status, total in db.execute(
                select(Run.status, func.count()).group_by(Run.status)
            ).all()
        }
        sample_id = next(iter(unique_claims))
        sample = db.get(Run, sample_id)
        assert sample is not None
        sample.worker_id = "fencer-a"
        sample.status = "running"
        sample.lease_until = time.time() - 1
    fenced = Runs(database, Resources(database))
    stale_claim = fenced.claim("fencer-b", 30)
    old_heartbeat = fenced.heartbeat(sample_id, "fencer-a", 30)
    try:
        fenced.finish(sample_id, "fencer-a", "completed", output={"late": True})
    except LeaseLost:
        old_finish_rejected = True
    else:  # pragma: no cover - a fencing regression
        old_finish_rejected = False
    with database.transaction() as db:
        final_status = db.get(Run, sample_id).status
    database.engine.dispose()

    return {
        "runs": count,
        "workers": workers,
        "claims": len(claimed),
        "unique_claims": len(unique_claims),
        "duplicate_claims": len(claimed) - len(unique_claims),
        "elapsed_seconds": round(elapsed, 4),
        "claims_per_second": round(len(claimed) / elapsed, 2) if elapsed else 0,
        "errors": errors,
        "statuses_after_claim": statuses,
        "fencing": {
            "stale_claim_rejected": stale_claim is None,
            "old_heartbeat_rejected": old_heartbeat is False,
            "old_finish_rejected": old_finish_rejected,
            "stale_run_terminal_status": final_status,
        },
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--runs", type=int, default=128, help="queued runs to create")
    parser.add_argument("--workers", type=int, default=8, help="concurrent claimers")
    parser.add_argument("--data-dir", type=Path, help="keep the SQLite database at this path")
    args = parser.parse_args()
    if args.data_dir:
        report = run_stress(args.data_dir, args.runs, args.workers)
        print(json.dumps(report, ensure_ascii=False, sort_keys=True))
        return
    with tempfile.TemporaryDirectory(prefix="eivon-stress-") as directory:
        report = run_stress(Path(directory), args.runs, args.workers)
        print(json.dumps(report, ensure_ascii=False, sort_keys=True))


if __name__ == "__main__":
    main()
