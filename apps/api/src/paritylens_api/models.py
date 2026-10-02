"""Database tables.

SQLAlchemy's ORM, in its typed 2.0 style: each class is a table, each
`Mapped[...]` attribute a column. Enumerations are stored as plain strings
and validated by the application, so adding a value needs no migration.

Ownership runs through `projects.workspace_id`. Every other table hangs
off a project, and every query that reaches one joins back to the project
to check the workspace (see repositories/).
"""

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    LargeBinary,
    MetaData,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    # Explicit constraint names, so migrations can refer to them.
    metadata = MetaData(
        naming_convention={
            "ix": "ix_%(column_0_label)s",
            "uq": "uq_%(table_name)s_%(column_0_name)s",
            "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
            "pk": "pk_%(table_name)s",
        }
    )
    type_annotation_map = {dict[str, Any]: JSONB, list[Any]: JSONB}  # noqa: RUF012


def _id() -> Mapped[uuid.UUID]:
    # Random IDs: nothing about one row can be guessed from another.
    return mapped_column(primary_key=True, default=uuid.uuid4)


# clock_timestamp() is the time the statement runs. now() would be the time
# the transaction began, giving every row written in one request the same
# value and leaving their order undefined.
_NOW = func.clock_timestamp()


def _created_at() -> Mapped[datetime]:
    return mapped_column(DateTime(timezone=True), server_default=_NOW)


def _updated_at() -> Mapped[datetime]:
    return mapped_column(DateTime(timezone=True), server_default=_NOW, onupdate=_NOW)


def _fk(target: str, *, nullable: bool = False, ondelete: str = "CASCADE") -> Mapped[Any]:
    return mapped_column(ForeignKey(target, ondelete=ondelete), nullable=nullable, index=True)


# --- identity ------------------------------------------------------------------


class User(Base):
    __tablename__ = "users"

    id: Mapped[uuid.UUID] = _id()
    email: Mapped[str] = mapped_column(String(320), unique=True)
    name: Mapped[str] = mapped_column(String(200), default="")
    # Google's stable identifier for the account. Email can change; this cannot.
    google_sub: Mapped[str | None] = mapped_column(String(255), unique=True)
    created_at: Mapped[datetime] = _created_at()


class Workspace(Base):
    __tablename__ = "workspaces"

    id: Mapped[uuid.UUID] = _id()
    name: Mapped[str] = mapped_column(String(200))
    created_at: Mapped[datetime] = _created_at()


class WorkspaceMember(Base):
    __tablename__ = "workspace_members"

    workspace_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("workspaces.id", ondelete="CASCADE"), primary_key=True
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), primary_key=True, index=True
    )
    role: Mapped[str] = mapped_column(String(20), default="owner")
    created_at: Mapped[datetime] = _created_at()


class Session(Base):
    """A signed-in browser. The cookie holds the token; this holds its hash."""

    __tablename__ = "sessions"

    id: Mapped[uuid.UUID] = _id()
    user_id: Mapped[uuid.UUID] = _fk("users.id")
    token_hash: Mapped[str] = mapped_column(String(64), unique=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = _created_at()


class ApiToken(Base):
    """A long-lived credential for the CLI, scoped to one workspace."""

    __tablename__ = "api_tokens"

    id: Mapped[uuid.UUID] = _id()
    workspace_id: Mapped[uuid.UUID] = _fk("workspaces.id")
    user_id: Mapped[uuid.UUID] = _fk("users.id")
    name: Mapped[str] = mapped_column(String(100))
    token_hash: Mapped[str] = mapped_column(String(64), unique=True)
    # The first characters, kept in the clear so a user can tell tokens apart.
    token_hint: Mapped[str] = mapped_column(String(16))
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = _created_at()


# --- configuration ---------------------------------------------------------------


class Project(Base):
    __tablename__ = "projects"

    id: Mapped[uuid.UUID] = _id()
    workspace_id: Mapped[uuid.UUID] = _fk("workspaces.id")
    name: Mapped[str] = mapped_column(String(200))
    description: Mapped[str] = mapped_column(Text, default="")
    old_base_url: Mapped[str] = mapped_column(String(2000))
    new_base_url: Mapped[str] = mapped_column(String(2000))
    # Headers sent to each side. Values may refer to secrets as {{secret.NAME}}.
    old_headers: Mapped[dict[str, Any]] = mapped_column(default=dict)
    new_headers: Mapped[dict[str, Any]] = mapped_column(default=dict)
    openapi_spec: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    critical_field_names: Mapped[bool] = mapped_column(Boolean, default=True)
    ai_enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = _created_at()
    updated_at: Mapped[datetime] = _updated_at()


class Endpoint(Base):
    __tablename__ = "endpoints"
    __table_args__ = (UniqueConstraint("project_id", "method", "path_template"),)

    id: Mapped[uuid.UUID] = _id()
    project_id: Mapped[uuid.UUID] = _fk("projects.id")
    method: Mapped[str] = mapped_column(String(10))
    path_template: Mapped[str] = mapped_column(String(2000))
    summary: Mapped[str] = mapped_column(String(500), default="")
    source: Mapped[str] = mapped_column(String(20), default="manual")  # manual | openapi
    created_at: Mapped[datetime] = _created_at()


class Rule(Base):
    __tablename__ = "rules"

    id: Mapped[uuid.UUID] = _id()
    project_id: Mapped[uuid.UUID] = _fk("projects.id")
    kind: Mapped[str] = mapped_column(String(20))  # ignore | unordered | critical | compare_header
    # A path pattern, or a header name for compare_header.
    path: Mapped[str] = mapped_column(String(1000))
    options: Mapped[dict[str, Any]] = mapped_column(default=dict)  # unordered: {"key": "sku"}
    created_at: Mapped[datetime] = _created_at()


class Secret(Base):
    """A credential for an API under test, encrypted. Its value is never read back out."""

    __tablename__ = "secrets"
    __table_args__ = (UniqueConstraint("project_id", "name"),)

    id: Mapped[uuid.UUID] = _id()
    project_id: Mapped[uuid.UUID] = _fk("projects.id")
    name: Mapped[str] = mapped_column(String(100))
    ciphertext: Mapped[bytes] = mapped_column(LargeBinary)
    nonce: Mapped[bytes] = mapped_column(LargeBinary)
    key_version: Mapped[int] = mapped_column(Integer)
    created_at: Mapped[datetime] = _created_at()
    updated_at: Mapped[datetime] = _updated_at()


class TestCase(Base):
    __tablename__ = "test_cases"
    __test__ = False  # tell pytest this is not a test class

    id: Mapped[uuid.UUID] = _id()
    project_id: Mapped[uuid.UUID] = _fk("projects.id")
    endpoint_id: Mapped[uuid.UUID | None] = _fk("endpoints.id", nullable=True, ondelete="SET NULL")
    name: Mapped[str] = mapped_column(String(200))
    # The engine's Step models as JSON, validated before every write.
    steps: Mapped[list[Any]] = mapped_column()
    noise_detection: Mapped[bool] = mapped_column(Boolean, default=True)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = _created_at()
    updated_at: Mapped[datetime] = _updated_at()


# --- results -------------------------------------------------------------------


class Run(Base):
    """One execution of a project's test cases. Also the job queue for hosted runs."""

    __tablename__ = "runs"
    __table_args__ = (
        # The worker's "next queued run" query.
        Index("ix_runs_status_created_at", "status", "created_at"),
    )

    id: Mapped[uuid.UUID] = _id()
    project_id: Mapped[uuid.UUID] = _fk("projects.id")
    created_by: Mapped[uuid.UUID | None] = _fk("users.id", nullable=True, ondelete="SET NULL")
    source: Mapped[str] = mapped_column(String(10))  # hosted | cli
    status: Mapped[str] = mapped_column(String(10))  # queued | running | completed | failed
    # none | pending | running | completed | failed | skipped
    ai_status: Mapped[str] = mapped_column(String(10), default="none")
    ai_error: Mapped[str | None] = mapped_column(Text)
    old_base_url: Mapped[str] = mapped_column(String(2000))
    new_base_url: Mapped[str] = mapped_column(String(2000))
    # What was run, frozen at the moment the run was requested, so the
    # result stays explainable after the project changes.
    rules_snapshot: Mapped[dict[str, Any]] = mapped_column(default=dict)
    suite_snapshot: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    summary: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    engine_version: Mapped[str | None] = mapped_column(String(20))
    error: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = _created_at()
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    cases: Mapped[list["CaseResult"]] = relationship(
        back_populates="run", order_by="CaseResult.position", cascade="all, delete-orphan"
    )


class CaseResult(Base):
    __tablename__ = "case_results"

    id: Mapped[uuid.UUID] = _id()
    run_id: Mapped[uuid.UUID] = _fk("runs.id")
    # Null once the test case has been deleted; the result outlives it.
    test_case_id: Mapped[uuid.UUID | None] = _fk(
        "test_cases.id", nullable=True, ondelete="SET NULL"
    )
    position: Mapped[int] = mapped_column(Integer)
    name: Mapped[str] = mapped_column(String(200))
    verdict: Mapped[str] = mapped_column(String(12))
    max_severity: Mapped[str] = mapped_column(String(10))

    run: Mapped[Run] = relationship(back_populates="cases")
    steps: Mapped[list["StepResult"]] = relationship(
        back_populates="case", order_by="StepResult.position", cascade="all, delete-orphan"
    )


class StepResult(Base):
    __tablename__ = "step_results"

    id: Mapped[uuid.UUID] = _id()
    case_result_id: Mapped[uuid.UUID] = _fk("case_results.id")
    position: Mapped[int] = mapped_column(Integer)
    step_id: Mapped[str] = mapped_column(String(200))
    outcome: Mapped[str] = mapped_column(String(10))
    # The engine's SideResult as JSON: request, response, error, skipped.
    old: Mapped[dict[str, Any]] = mapped_column()
    new: Mapped[dict[str, Any]] = mapped_column()
    notes: Mapped[list[Any]] = mapped_column(default=list)

    case: Mapped[CaseResult] = relationship(back_populates="steps")
    differences: Mapped[list["Difference"]] = relationship(
        back_populates="step", order_by="Difference.position", cascade="all, delete-orphan"
    )


class Difference(Base):
    """One difference, as its own row so that it can be filtered and counted."""

    __tablename__ = "differences"
    __table_args__ = (Index("ix_differences_run_id_severity", "run_id", "severity"),)

    id: Mapped[uuid.UUID] = _id()
    step_result_id: Mapped[uuid.UUID] = _fk("step_results.id")
    # Repeated from the run so that "all differences of a run" needs no joins.
    run_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("runs.id", ondelete="CASCADE"))
    position: Mapped[int] = mapped_column(Integer)
    kind: Mapped[str] = mapped_column(String(30))
    path: Mapped[str] = mapped_column(Text)
    old_value: Mapped[Any] = mapped_column(JSONB, nullable=True)
    new_value: Mapped[Any] = mapped_column(JSONB, nullable=True)
    detail: Mapped[str | None] = mapped_column(Text)
    severity: Mapped[str] = mapped_column(String(10))
    reason: Mapped[str] = mapped_column(String(30))
    noise_source: Mapped[str | None] = mapped_column(String(10))
    hints: Mapped[list[Any]] = mapped_column(default=list)
    # "<kind>:<path with array positions generalised>". The same finding in
    # different cases, or at different positions of an array, shares one.
    signature: Mapped[str] = mapped_column(Text, default="")

    step: Mapped[StepResult] = relationship(back_populates="differences")


class AiAnalysis(Base):
    """What a language model said about one finding of a run.

    Kept in its own table, apart from the differences it comments on. The
    deterministic result is in `differences`; nothing here feeds back into
    it. Deleting every row of this table changes no verdict and no score.
    """

    __tablename__ = "ai_analyses"
    __table_args__ = (UniqueConstraint("run_id", "signature"),)

    id: Mapped[uuid.UUID] = _id()
    run_id: Mapped[uuid.UUID] = _fk("runs.id")
    signature: Mapped[str] = mapped_column(Text)
    verdict: Mapped[str] = mapped_column(String(10))  # safe | warning | breaking
    confidence: Mapped[str] = mapped_column(String(10))  # low | medium | high
    explanation: Mapped[str] = mapped_column(Text)
    # Which model said it, and with which prompt, so an opinion can be
    # traced and old ones told apart after either changes.
    provider: Mapped[str] = mapped_column(String(30))
    model: Mapped[str] = mapped_column(String(100))
    prompt_version: Mapped[str] = mapped_column(String(20))
    created_at: Mapped[datetime] = _created_at()
