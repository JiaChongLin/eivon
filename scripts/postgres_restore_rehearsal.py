"""Run a destructive PostgreSQL backup/restore check against a disposable database."""

from __future__ import annotations

import json
import os
from pathlib import Path

from eivon.server.backup import postgres_backup, postgres_restore
from eivon.server.settings import Settings


def main() -> None:
    try:
        import psycopg
    except ImportError as exc:  # pragma: no cover - exercised by the optional CI job
        raise SystemExit("Install the postgres extra before running this rehearsal") from exc
    database_url = os.getenv("EIVON_DATABASE_URL", "")
    if not database_url.startswith("postgresql"):
        raise SystemExit("EIVON_DATABASE_URL must point to a disposable PostgreSQL database")
    data_dir = Path(os.getenv("EIVON_DATA_DIR", "var/postgres-rehearsal"))
    dump_path = Path(os.getenv("EIVON_REHEARSAL_DUMP", "/tmp/eivon-postgres-rehearsal.dump"))
    settings = Settings(data_dir=data_dir, database_url=database_url)

    with psycopg.connect(database_url) as connection:
        connection.execute("CREATE TABLE IF NOT EXISTS eivon_rehearsal_marker (value text NOT NULL)")
        connection.execute("TRUNCATE eivon_rehearsal_marker")
        connection.execute("INSERT INTO eivon_rehearsal_marker (value) VALUES ('before-restore')")
        connection.commit()

    backup_result = postgres_backup(settings, dump_path)
    with psycopg.connect(database_url) as connection:
        connection.execute("UPDATE eivon_rehearsal_marker SET value = 'changed-after-backup'")
        connection.commit()
    restore_result = postgres_restore(settings, dump_path, force=True)

    with psycopg.connect(database_url) as connection:
        value = connection.execute("SELECT value FROM eivon_rehearsal_marker").fetchone()[0]
    if value != "before-restore":
        raise SystemExit(f"PostgreSQL restore verification failed: {value!r}")
    print(json.dumps({"backup": backup_result, "restore": restore_result, "marker": value}))


if __name__ == "__main__":
    main()
