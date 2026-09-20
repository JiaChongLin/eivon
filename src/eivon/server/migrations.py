"""Small, explicit schema migration boundary for self-hosted deployments.

The version gate rejects newer schemas before any schema changes. Known releases
receive additive tables and the legacy result-to-job column migration.
"""

from __future__ import annotations

from sqlalchemy import inspect, text
from sqlalchemy.exc import IntegrityError

from .db import Base, Database, Meta

CURRENT_SCHEMA_VERSION = 4


def upgrade(database: Database) -> int:
    """Apply all migrations and return the resulting schema version.

    Version 1 is the initial metadata bootstrap, version 2 adds persisted
    evaluation results, version 3 links results to durable evaluation Jobs, and
    version 4 adds append-only human reviews and reviewed improvement proposals.
    Existing databases are upgraded idempotently; unknown versions fail closed.
    """

    if inspect(database.engine).has_table(Meta.__tablename__):
        with database.transaction() as session:
            version = session.get(Meta, "schema_version")
            if version is not None and version.value not in {"1", "2", "3", "4"}:
                raise RuntimeError(
                    f"Unsupported database schema version; expected {CURRENT_SCHEMA_VERSION}"
                )
    Base.metadata.create_all(database.engine)
    columns = {
        column["name"] for column in inspect(database.engine).get_columns("evaluation_results")
    }
    if "job_id" not in columns:
        with database.engine.begin() as connection:
            connection.execute(text("ALTER TABLE evaluation_results ADD COLUMN job_id VARCHAR(32)"))
        with database.engine.begin() as connection:
            connection.execute(
                text(
                    "CREATE INDEX IF NOT EXISTS ix_evaluation_results_job_id "
                    "ON evaluation_results (job_id)"
                )
            )
    try:
        with database.transaction() as session:
            version = session.get(Meta, "schema_version")
            if version is None:
                session.add(Meta(key="schema_version", value=str(CURRENT_SCHEMA_VERSION)))
            elif int(version.value) in {1, 2, 3}:
                version.value = str(CURRENT_SCHEMA_VERSION)
            if session.get(Meta, "initialized") is None:
                session.add(Meta(key="initialized", value="false"))
    except IntegrityError:
        # Another API or worker process may have inserted the bootstrap rows.
        pass
    with database.transaction() as session:
        item = session.get(Meta, "schema_version")
        if item is None or int(item.value) != CURRENT_SCHEMA_VERSION:
            raise RuntimeError(
                f"Unsupported database schema version; expected {CURRENT_SCHEMA_VERSION}"
            )
    return CURRENT_SCHEMA_VERSION
