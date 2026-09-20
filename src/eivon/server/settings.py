"""Explicit application configuration with portable local defaults."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path


@dataclass(frozen=True)
class Settings:
    data_dir: Path = field(default_factory=lambda: Path(os.getenv("EIVON_DATA_DIR", "var")))
    database_url: str = field(default_factory=lambda: os.getenv("EIVON_DATABASE_URL", ""))
    secret_key: str = field(default_factory=lambda: os.getenv("EIVON_SECRET_KEY", ""))
    setup_token: str = field(default_factory=lambda: os.getenv("EIVON_SETUP_TOKEN", ""))
    secure_cookies: bool = field(
        default_factory=lambda: os.getenv("EIVON_SECURE_COOKIES", "false").lower() == "true"
    )
    allowed_hosts: tuple[str, ...] = field(
        default_factory=lambda: tuple(
            x.strip() for x in os.getenv("EIVON_OUTBOUND_HOSTS", "").split(",") if x.strip()
        )
    )
    extensions: tuple[str, ...] = field(
        default_factory=lambda: tuple(
            x.strip() for x in os.getenv("EIVON_EXTENSIONS", "").split(",") if x.strip()
        )
    )
    inline_worker: bool = field(
        default_factory=lambda: os.getenv("EIVON_INLINE_WORKER", "true").lower() == "true"
    )
    worker_poll_seconds: float = 0.5
    lease_seconds: int = 60
    max_upload_bytes: int = 10 * 1024 * 1024
    console_dir: Path | None = None
    testing: bool = False

    @property
    def db_url(self) -> str:
        return self.database_url or f"sqlite:///{self.data_dir.resolve() / 'eivon.db'}"
