"""Run history queries."""
import uuid
from datetime import datetime, timezone

from sqlalchemy import select

from app.database.session import session
from app.models.tables import Run


def _iso(dt: datetime | None) -> str | None:
    if dt is None:
        return None
    return (dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)).isoformat()


def _title(r: Run) -> str:
    if r.task.strip():
        return r.task.strip()[:200]
    return f"GitHub issue #{r.issue_number} in {r.github_repo}" if r.issue_number else "(no task)"


def _summary(r: Run) -> dict:
    duration = None
    if r.finished_at:
        a = r.created_at if r.created_at.tzinfo else r.created_at.replace(tzinfo=timezone.utc)
        b = r.finished_at if r.finished_at.tzinfo else r.finished_at.replace(tzinfo=timezone.utc)
        duration = int((b - a).total_seconds() * 1000)
    return {"id": r.id, "created_at": _iso(r.created_at), "status": r.status, "repo_id": r.repo_id,
            "title": _title(r), "has_proposal": bool(r.proposal_id), "duration_ms": duration, "error": r.error}


def create_run(repo_id: str, task: str, github_repo: str | None, issue_number: int | None) -> str:
    run_id = uuid.uuid4().hex
    with session() as s:
        s.add(Run(id=run_id, repo_id=repo_id, task=task, github_repo=github_repo, issue_number=issue_number,
                  events=[]))
    return run_id


def finish_run(run_id: str, status: str, error: str, proposal_id: str | None, events: list[dict]) -> None:
    with session() as s:
        r = s.get(Run, run_id)
        if r:
            r.status, r.error, r.proposal_id, r.events = status, error[:2000], proposal_id, list(events)
            r.finished_at = datetime.now(timezone.utc)


def list_runs(limit: int = 30, repo_id: str | None = None) -> list[dict]:
    q = select(Run).order_by(Run.created_at.desc()).limit(limit)
    if repo_id:
        q = q.where(Run.repo_id == repo_id)
    with session() as s:
        return [_summary(r) for r in s.scalars(q)]


def get_run(run_id: str) -> dict | None:
    with session() as s:
        r = s.get(Run, run_id)
        if not r:
            return None
        return {**_summary(r), "task": r.task, "github_repo": r.github_repo, "issue_number": r.issue_number,
                "proposal_id": r.proposal_id, "events": r.events}


def delete_run(run_id: str) -> bool:
    with session() as s:
        r = s.get(Run, run_id)
        if not r:
            return False
        s.delete(r)
        return True