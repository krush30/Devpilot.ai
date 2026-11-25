import uuid

from sqlalchemy import select

from app.database.session import session
from app.models.tables import SandboxRun


def save_result(proposal_id: str, status: str, result: dict) -> str:
    rid = uuid.uuid4().hex
    with session() as s:
        s.add(SandboxRun(id=rid, proposal_id=proposal_id, status=status, result=result))
    return rid


def latest(proposal_id: str) -> dict | None:
    q = select(SandboxRun).where(SandboxRun.proposal_id == proposal_id).order_by(SandboxRun.created_at.desc()).limit(1)
    with session() as s:
        row = s.scalars(q).first()
        return {**row.result, "id": row.id, "created_at": row.created_at.isoformat()} if row else None