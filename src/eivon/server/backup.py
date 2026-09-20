"""Database and artifact backup/restore helpers for self-hosted deployments."""

from __future__ import annotations

import json
import os
import shutil
import sqlite3
import subprocess
import tarfile
import tempfile
import time
from pathlib import Path

from .migrations import CURRENT_SCHEMA_VERSION
from .settings import Settings


class BackupError(RuntimeError):
    pass


def _database_path(settings: Settings) -> Path:
    if not settings.db_url.startswith("sqlite:///"):
        raise BackupError("SQLite archive operations require EIVON_DATABASE_URL to be empty")
    return Path(settings.db_url.removeprefix("sqlite:///"))


def _safe_members(archive: tarfile.TarFile, root: Path) -> list[tarfile.TarInfo]:
    members = archive.getmembers()
    root = root.resolve()
    for member in members:
        destination = (root / member.name).resolve()
        if root not in destination.parents and destination != root:
            raise BackupError("Backup contains an unsafe path")
        if member.issym() or member.islnk():
            raise BackupError("Backup links are not accepted")
    return members


def backup(settings: Settings, output: Path) -> dict:
    """Create an atomic tar archive containing a consistent SQLite copy and artifacts."""
    if not settings.db_url.startswith("sqlite:///"):
        raise BackupError(
            "Use pg_dump for PostgreSQL backups; Eivon does not copy a live server database"
        )
    source = _database_path(settings)
    if not source.exists():
        raise BackupError(f"Database does not exist: {source}")
    output = output.expanduser().resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="eivon-backup-") as directory:
        root = Path(directory)
        db_copy = root / "eivon.db"
        source_db = sqlite3.connect(source)
        target_db = sqlite3.connect(db_copy)
        try:
            source_db.backup(target_db)
        finally:
            target_db.close()
            source_db.close()
        artifacts = settings.data_dir / "artifacts"
        if artifacts.is_dir():
            shutil.copytree(artifacts, root / "artifacts")
        (root / "manifest.json").write_text(
            json.dumps(
                {"format": 1, "schema_version": CURRENT_SCHEMA_VERSION, "created_at": time.time()},
                indent=2,
            )
            + "\n"
        )
        temporary = output.with_suffix(output.suffix + ".tmp")
        with tarfile.open(temporary, "w:gz") as archive:
            for item in root.iterdir():
                archive.add(item, arcname=item.name)
        os.replace(temporary, output)
    return {
        "path": str(output),
        "schema_version": CURRENT_SCHEMA_VERSION,
        "bytes": output.stat().st_size,
    }


def restore(settings: Settings, archive_path: Path, force: bool = False) -> dict:
    """Restore a SQLite archive after validating its manifest and archive paths."""
    if not force:
        raise BackupError("Restore requires --force and must run with API/worker processes stopped")
    archive_path = archive_path.expanduser().resolve()
    if not archive_path.is_file():
        raise BackupError(f"Backup does not exist: {archive_path}")
    with tempfile.TemporaryDirectory(prefix="eivon-restore-") as directory:
        root = Path(directory)
        with tarfile.open(archive_path, "r:gz") as archive:
            _safe_members(archive, root)
            archive.extractall(root)
        manifest_path = root / "manifest.json"
        database_copy = root / "eivon.db"
        if not manifest_path.is_file() or not database_copy.is_file():
            raise BackupError("Backup is missing manifest.json or eivon.db")
        manifest = json.loads(manifest_path.read_text())
        if (
            manifest.get("format") != 1
            or int(manifest.get("schema_version", 0)) > CURRENT_SCHEMA_VERSION
        ):
            raise BackupError("Backup schema is newer than this Eivon binary")
        restored = _database_path(settings)
        restored.parent.mkdir(parents=True, exist_ok=True)
        temporary = restored.with_suffix(restored.suffix + ".restore")
        shutil.copy2(database_copy, temporary)
        os.replace(temporary, restored)
        artifacts = settings.data_dir / "artifacts"
        restored_artifacts = root / "artifacts"
        if restored_artifacts.is_dir():
            temporary_artifacts = artifacts.with_name("artifacts.restore")
            if temporary_artifacts.exists():
                shutil.rmtree(temporary_artifacts)
            shutil.copytree(restored_artifacts, temporary_artifacts)
            if artifacts.exists():
                shutil.rmtree(artifacts)
            os.replace(temporary_artifacts, artifacts)
    return {
        "path": str(archive_path),
        "schema_version": manifest["schema_version"],
        "restored": True,
    }


def postgres_backup(settings: Settings, output: Path) -> dict:
    if not settings.db_url.startswith("postgresql"):
        raise BackupError("pg_dump backup requires a PostgreSQL EIVON_DATABASE_URL")
    output.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        ["pg_dump", "--format=custom", "--file", str(output), settings.db_url], check=True
    )
    return {"path": str(output), "bytes": output.stat().st_size, "format": "postgres-custom"}


def postgres_restore(settings: Settings, archive_path: Path, force: bool = False) -> dict:
    """Restore a pg_dump custom archive into the configured PostgreSQL database."""
    if not settings.db_url.startswith("postgresql"):
        raise BackupError("pg_restore requires a PostgreSQL EIVON_DATABASE_URL")
    if not force:
        raise BackupError("Restore requires --force and must run with API/worker processes stopped")
    archive_path = archive_path.expanduser().resolve()
    if not archive_path.is_file():
        raise BackupError(f"Backup does not exist: {archive_path}")
    subprocess.run(
        [
            "pg_restore",
            "--clean",
            "--if-exists",
            "--no-owner",
            "--dbname",
            settings.db_url,
            str(archive_path),
        ],
        check=True,
    )
    return {"path": str(archive_path), "restored": True, "format": "postgres-custom"}
