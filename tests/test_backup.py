import json
import sqlite3
import tarfile
from pathlib import Path

import pytest

from eivon.server.backup import BackupError, backup, postgres_restore, restore
from eivon.server.settings import Settings


def test_sqlite_backup_restore_round_trip(tmp_path):
    settings = Settings(data_dir=tmp_path / "source", setup_token="setup")
    settings.data_dir.mkdir(parents=True)
    db_path = Path(settings.db_url.removeprefix("sqlite:///"))
    connection = sqlite3.connect(db_path)
    connection.execute("create table marker (value text)")
    connection.execute("insert into marker values ('sqlite fixture')")
    connection.commit()
    connection.close()
    (settings.data_dir / "artifacts").mkdir()
    (settings.data_dir / "artifacts" / "a1").write_bytes(b"artifact")
    archive = tmp_path / "backup.tar.gz"
    result = backup(settings, archive)
    assert result["schema_version"] == 6
    connection = sqlite3.connect(db_path)
    connection.execute("update marker set value='changed'")
    connection.commit()
    connection.close()
    (settings.data_dir / "artifacts" / "a1").write_bytes(b"changed")
    restored = restore(settings, archive, force=True)
    assert restored["restored"] is True
    connection = sqlite3.connect(db_path)
    assert connection.execute("select value from marker").fetchone()[0] == "sqlite fixture"
    connection.close()
    assert (settings.data_dir / "artifacts" / "a1").read_bytes() == b"artifact"


def test_restore_rejects_unsafe_archive_and_requires_force(tmp_path):
    settings = Settings(data_dir=tmp_path / "source")
    archive = tmp_path / "unsafe.tar.gz"
    with tarfile.open(archive, "w:gz") as handle:
        path = tmp_path / "manifest.json"
        path.write_text(json.dumps({"format": 1, "schema_version": 5}))
        handle.add(path, arcname="../manifest.json")
    with pytest.raises(BackupError, match="force"):
        restore(settings, archive)
    with pytest.raises(BackupError, match="unsafe"):
        restore(settings, archive, force=True)


def test_postgres_restore_requires_force_and_invokes_pg_restore(tmp_path, monkeypatch):
    from eivon.server import backup as backup_module

    archive = tmp_path / "eivon.dump"
    archive.write_bytes(b"custom dump")
    settings = Settings(
        data_dir=tmp_path / "postgres",
        database_url="postgresql+psycopg://eivon:test@db/eivon",
    )
    with pytest.raises(BackupError, match="force"):
        postgres_restore(settings, archive)
    calls = []
    monkeypatch.setattr(backup_module.subprocess, "run", lambda command, check: calls.append((command, check)))
    result = postgres_restore(settings, archive, force=True)
    assert result["restored"] is True
    assert calls[0][0][:4] == ["pg_restore", "--clean", "--if-exists", "--no-owner"]
    assert settings.db_url in calls[0][0]
