"""Persistence shared by the API and workers; SQLite and PostgreSQL supported."""

from __future__ import annotations

import time
import uuid
from contextlib import contextmanager
from typing import Any

from sqlalchemy import (
    JSON,
    Boolean,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    create_engine,
    event,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, sessionmaker

from .settings import Settings


def uid() -> str:
    return uuid.uuid4().hex


class Base(DeclarativeBase):
    pass


class Meta(Base):
    __tablename__ = "instance_meta"
    key: Mapped[str] = mapped_column(String(80), primary_key=True)
    value: Mapped[str] = mapped_column(Text)


class User(Base):
    __tablename__ = "users"
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=uid)
    email: Mapped[str] = mapped_column(String(254), unique=True)
    name: Mapped[str] = mapped_column(String(120))
    password_hash: Mapped[str] = mapped_column(Text)
    created_at: Mapped[float] = mapped_column(Float, default=time.time)


class Workspace(Base):
    __tablename__ = "workspaces"
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=uid)
    name: Mapped[str] = mapped_column(String(120))
    created_at: Mapped[float] = mapped_column(Float, default=time.time)


class Member(Base):
    __tablename__ = "memberships"
    workspace_id: Mapped[str] = mapped_column(ForeignKey("workspaces.id"), primary_key=True)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), primary_key=True)
    role: Mapped[str] = mapped_column(String(20))


class Token(Base):
    __tablename__ = "tokens"
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=uid)
    digest: Mapped[str] = mapped_column(String(64), unique=True)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True)
    workspace_id: Mapped[str | None] = mapped_column(ForeignKey("workspaces.id"), nullable=True)
    kind: Mapped[str] = mapped_column(String(20))
    name: Mapped[str] = mapped_column(String(120), default="Session")
    permissions: Mapped[list] = mapped_column(JSON, default=list)
    expires_at: Mapped[float] = mapped_column(Float)
    created_at: Mapped[float] = mapped_column(Float, default=time.time)


class LoginAttempt(Base):
    __tablename__ = "login_attempts"
    key: Mapped[str] = mapped_column(String(64), primary_key=True)
    failures: Mapped[int] = mapped_column(Integer, default=0)
    reset_at: Mapped[float] = mapped_column(Float)


class Credential(Base):
    __tablename__ = "credentials"
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=uid)
    workspace_id: Mapped[str] = mapped_column(ForeignKey("workspaces.id"), index=True)
    name: Mapped[str] = mapped_column(String(120))
    encrypted_value: Mapped[str] = mapped_column(Text)
    updated_at: Mapped[float] = mapped_column(Float, default=time.time)


class Resource(Base):
    __tablename__ = "resources"
    __table_args__ = (UniqueConstraint("workspace_id", "kind", "slug"),)
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=uid)
    workspace_id: Mapped[str] = mapped_column(ForeignKey("workspaces.id"), index=True)
    kind: Mapped[str] = mapped_column(String(30))
    slug: Mapped[str] = mapped_column(String(100))
    name: Mapped[str] = mapped_column(String(160))
    draft: Mapped[dict] = mapped_column(JSON)
    revision: Mapped[int] = mapped_column(Integer, default=1)
    latest_version: Mapped[int] = mapped_column(Integer, default=0)
    active_version: Mapped[int | None] = mapped_column(Integer, nullable=True)
    archived: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[float] = mapped_column(Float, default=time.time)
    updated_at: Mapped[float] = mapped_column(Float, default=time.time)


class ResourceVersion(Base):
    __tablename__ = "resource_versions"
    resource_id: Mapped[str] = mapped_column(ForeignKey("resources.id"), primary_key=True)
    version: Mapped[int] = mapped_column(Integer, primary_key=True)
    spec: Mapped[dict] = mapped_column(JSON)
    snapshot: Mapped[dict] = mapped_column(JSON)
    digest: Mapped[str] = mapped_column(String(64))
    created_by: Mapped[str] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[float] = mapped_column(Float, default=time.time)


class Session(Base):
    __tablename__ = "sessions"
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=uid)
    workspace_id: Mapped[str] = mapped_column(ForeignKey("workspaces.id"), index=True)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True)
    agent_id: Mapped[str] = mapped_column(ForeignKey("resources.id"))
    title: Mapped[str] = mapped_column(String(200), default="New conversation")
    context: Mapped[dict] = mapped_column(JSON, default=dict)
    active_run_id: Mapped[str | None] = mapped_column(String(32), nullable=True)
    created_at: Mapped[float] = mapped_column(Float, default=time.time)
    updated_at: Mapped[float] = mapped_column(Float, default=time.time)


class Run(Base):
    __tablename__ = "runs"
    __table_args__ = (
        UniqueConstraint("workspace_id", "user_id", "idempotency_key"),
        Index("ix_runs_queue", "status", "created_at"),
    )
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=uid)
    workspace_id: Mapped[str] = mapped_column(ForeignKey("workspaces.id"), index=True)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"))
    session_id: Mapped[str | None] = mapped_column(
        ForeignKey("sessions.id"), nullable=True, index=True
    )
    resource_id: Mapped[str] = mapped_column(ForeignKey("resources.id"))
    resource_version: Mapped[int] = mapped_column(Integer)
    kind: Mapped[str] = mapped_column(String(20), default="agent")
    status: Mapped[str] = mapped_column(String(30), default="queued")
    snapshot: Mapped[dict] = mapped_column(JSON)
    input: Mapped[dict] = mapped_column(JSON, default=dict)
    output: Mapped[dict] = mapped_column(JSON, default=dict)
    checkpoint: Mapped[dict] = mapped_column(JSON, default=dict)
    usage: Mapped[dict] = mapped_column(JSON, default=dict)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    idempotency_key: Mapped[str | None] = mapped_column(String(100), nullable=True)
    cancel_requested: Mapped[bool] = mapped_column(Boolean, default=False)
    worker_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    lease_until: Mapped[float | None] = mapped_column(Float, nullable=True)
    event_sequence: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[float] = mapped_column(Float, default=time.time)
    started_at: Mapped[float | None] = mapped_column(Float, nullable=True)
    finished_at: Mapped[float | None] = mapped_column(Float, nullable=True)


class RunEvent(Base):
    __tablename__ = "run_events"
    run_id: Mapped[str] = mapped_column(ForeignKey("runs.id"), primary_key=True)
    sequence: Mapped[int] = mapped_column(Integer, primary_key=True)
    type: Mapped[str] = mapped_column(String(40))
    data: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[float] = mapped_column(Float, default=time.time)


class Artifact(Base):
    __tablename__ = "artifacts"
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=uid)
    workspace_id: Mapped[str] = mapped_column(ForeignKey("workspaces.id"), index=True)
    run_id: Mapped[str | None] = mapped_column(ForeignKey("runs.id"), nullable=True)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"))
    name: Mapped[str] = mapped_column(String(200))
    media_type: Mapped[str] = mapped_column(String(120))
    size: Mapped[int] = mapped_column(Integer)
    digest: Mapped[str] = mapped_column(String(64))
    created_at: Mapped[float] = mapped_column(Float, default=time.time)


class Collection(Base):
    __tablename__ = "knowledge_collections"
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=uid)
    workspace_id: Mapped[str] = mapped_column(ForeignKey("workspaces.id"), index=True)
    name: Mapped[str] = mapped_column(String(160))
    description: Mapped[str] = mapped_column(Text, default="")
    connection_id: Mapped[str | None] = mapped_column(String(32), nullable=True)
    connection_version: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[float] = mapped_column(Float, default=time.time)


class Document(Base):
    __tablename__ = "knowledge_documents"
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=uid)
    collection_id: Mapped[str] = mapped_column(ForeignKey("knowledge_collections.id"), index=True)
    title: Mapped[str] = mapped_column(String(200))
    content: Mapped[str] = mapped_column(Text)
    source_uri: Mapped[str] = mapped_column(Text, default="")
    digest: Mapped[str] = mapped_column(String(64))
    status: Mapped[str] = mapped_column(String(20), default="pending")
    created_at: Mapped[float] = mapped_column(Float, default=time.time)


class Chunk(Base):
    __tablename__ = "knowledge_chunks"
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=uid)
    document_id: Mapped[str] = mapped_column(ForeignKey("knowledge_documents.id"), index=True)
    position: Mapped[int] = mapped_column(Integer)
    content: Mapped[str] = mapped_column(Text)
    terms: Mapped[dict] = mapped_column(JSON)
    embedding: Mapped[list] = mapped_column(JSON, default=list)


class Job(Base):
    __tablename__ = "jobs"
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=uid)
    workspace_id: Mapped[str] = mapped_column(ForeignKey("workspaces.id"), index=True)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"))
    kind: Mapped[str] = mapped_column(String(30))
    status: Mapped[str] = mapped_column(String(20), default="queued")
    input: Mapped[dict] = mapped_column(JSON)
    output: Mapped[dict] = mapped_column(JSON, default=dict)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    worker_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    lease_until: Mapped[float | None] = mapped_column(Float, nullable=True)
    created_at: Mapped[float] = mapped_column(Float, default=time.time)
    finished_at: Mapped[float | None] = mapped_column(Float, nullable=True)


class EvaluationSet(Base):
    __tablename__ = "evaluation_sets"
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=uid)
    workspace_id: Mapped[str] = mapped_column(ForeignKey("workspaces.id"), index=True)
    name: Mapped[str] = mapped_column(String(160))
    cases: Mapped[list] = mapped_column(JSON)
    revision: Mapped[int] = mapped_column(Integer, default=1)
    created_at: Mapped[float] = mapped_column(Float, default=time.time)


class EvaluationResult(Base):
    __tablename__ = "evaluation_results"
    __table_args__ = (UniqueConstraint("job_id", "case_index"),)
    job_id: Mapped[str | None] = mapped_column(ForeignKey("jobs.id"), nullable=True, index=True)
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=uid)
    evaluation_set_id: Mapped[str] = mapped_column(ForeignKey("evaluation_sets.id"), index=True)
    workspace_id: Mapped[str] = mapped_column(ForeignKey("workspaces.id"), index=True)
    resource_id: Mapped[str] = mapped_column(String(32), index=True)
    resource_version: Mapped[int] = mapped_column(Integer)
    case_index: Mapped[int] = mapped_column(Integer)
    run_id: Mapped[str | None] = mapped_column(ForeignKey("runs.id"), nullable=True, index=True)
    input: Mapped[dict] = mapped_column(JSON, default=dict)
    expected: Mapped[str] = mapped_column(Text, default="")
    actual: Mapped[str] = mapped_column(Text, default="")
    score: Mapped[float] = mapped_column(Float, default=0.0)
    status: Mapped[str] = mapped_column(String(20), default="pending")
    created_at: Mapped[float] = mapped_column(Float, default=time.time)


class EvaluationReview(Base):
    __tablename__ = "evaluation_reviews"
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=uid)
    result_id: Mapped[str] = mapped_column(ForeignKey("evaluation_results.id"), index=True)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"))
    score: Mapped[float] = mapped_column(Float)
    note: Mapped[str] = mapped_column(Text)
    created_at: Mapped[float] = mapped_column(Float, default=time.time)


class ImprovementProposal(Base):
    __tablename__ = "improvement_proposals"
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=uid)
    workspace_id: Mapped[str] = mapped_column(ForeignKey("workspaces.id"), index=True)
    job_id: Mapped[str] = mapped_column(ForeignKey("jobs.id"), index=True)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"))
    resource_id: Mapped[str] = mapped_column(ForeignKey("resources.id"))
    base_revision: Mapped[int] = mapped_column(Integer)
    base_spec: Mapped[dict] = mapped_column(JSON)
    candidate_spec: Mapped[dict] = mapped_column(JSON)
    rationale: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(20), default="pending")
    reviewer_id: Mapped[str | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    review_note: Mapped[str] = mapped_column(Text, default="")
    applied_revision: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[float] = mapped_column(Float, default=time.time)
    reviewed_at: Mapped[float | None] = mapped_column(Float, nullable=True)


class LearningItem(Base):
    __tablename__ = "learning_items"
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=uid)
    workspace_id: Mapped[str] = mapped_column(ForeignKey("workspaces.id"), index=True)
    run_id: Mapped[str] = mapped_column(ForeignKey("runs.id"))
    title: Mapped[str] = mapped_column(String(200))
    body: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(20), default="candidate")
    created_at: Mapped[float] = mapped_column(Float, default=time.time)


class AuditEvent(Base):
    __tablename__ = "audit_events"
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=uid)
    workspace_id: Mapped[str | None] = mapped_column(
        ForeignKey("workspaces.id"), index=True, nullable=True
    )
    user_id: Mapped[str | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    action: Mapped[str] = mapped_column(String(80))
    target_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    details: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[float] = mapped_column(Float, default=time.time)


def row_dict(row: Any, exclude: tuple[str, ...] = ()) -> dict:
    return {
        column.name: getattr(row, column.name)
        for column in row.__table__.columns
        if column.name not in exclude
    }


class Database:
    def __init__(self, settings: Settings):
        settings.data_dir.mkdir(parents=True, exist_ok=True)
        kwargs: dict = {}
        if settings.db_url.startswith("sqlite"):
            kwargs["connect_args"] = {"check_same_thread": False, "timeout": 30}
        self.engine = create_engine(settings.db_url, pool_pre_ping=True, **kwargs)
        if settings.db_url.startswith("sqlite"):

            @event.listens_for(self.engine, "connect")
            def sqlite_options(connection, _record):
                connection.execute("PRAGMA foreign_keys=ON")
                connection.execute("PRAGMA journal_mode=WAL")

        self.factory = sessionmaker(self.engine, expire_on_commit=False)

    def initialize(self) -> None:
        from .migrations import upgrade

        upgrade(self)

    @contextmanager
    def transaction(self):
        with self.factory() as db:
            with db.begin():
                yield db
