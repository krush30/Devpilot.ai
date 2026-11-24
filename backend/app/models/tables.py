"""Database tables. JSON columns work on both SQLite and PostgreSQL."""
from datetime import datetime, timezone

from sqlalchemy import JSON, DateTime, Integer, String, Text
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Base(DeclarativeBase):
    pass


class Run(Base):
    """One execution of the agent graph, with every event it streamed (replayable in the UI)."""
    __tablename__ = "runs"

    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    repo_id: Mapped[str] = mapped_column(String(120), index=True)
    task: Mapped[str] = mapped_column(Text, default="")
    github_repo: Mapped[str | None] = mapped_column(String(200), nullable=True)
    issue_number: Mapped[int | None] = mapped_column(Integer, nullable=True)
    status: Mapped[str] = mapped_column(String(20), default="running")  # running|done|needs_input|error|cancelled|interrupted
    error: Mapped[str] = mapped_column(Text, default="")
    proposal_id: Mapped[str | None] = mapped_column(String(24), nullable=True)
    events: Mapped[list] = mapped_column(JSON, default=list)  # agent events only: no raw code


class ProposalRow(Base):
    """A proposal the agents produced. Holds the raw old/new code, which never goes to the browser."""
    __tablename__ = "proposals"

    id: Mapped[str] = mapped_column(String(24), primary_key=True)
    repo_id: Mapped[str] = mapped_column(String(120), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)
    proposal: Mapped[dict] = mapped_column(JSON)
    review: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    applied: Mapped[list] = mapped_column(JSON, default=list)  # [{index, path, sha, original_b64}] for undo