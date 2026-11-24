"""Server-side store of agent proposals (database-backed since Week 6).

The approval endpoint applies exactly what the agents produced. The browser only says
"apply proposal X, changes 0 and 2"; it never sends code to write. Proposals, and the
undo information for applied changes, now survive backend restarts.
"""
import base64
import secrets
import threading

from app.database.session import session
from app.models.tables import ProposalRow


def _encode(undo: dict) -> dict:
    original = undo["original"]
    return {"path": undo["path"], "sha": undo["sha"],
            "original_b64": None if original is None else base64.b64encode(original).decode()}


def _decode(entry: dict) -> dict:
    b64 = entry["original_b64"]
    return {"path": entry["path"], "sha": entry["sha"], "original": None if b64 is None else base64.b64decode(b64)}


class ProposalStore:
    def __init__(self) -> None:
        self.lock = threading.RLock()  # serialises apply/undo

    def save(self, repo_id: str, proposal: dict, review: dict | None = None) -> str:
        pid = secrets.token_urlsafe(9)
        with session() as s:
            s.add(ProposalRow(id=pid, repo_id=repo_id, proposal=proposal, review=review, applied=[]))
        return pid

    def get(self, pid: str) -> dict | None:
        with session() as s:
            row = s.get(ProposalRow, pid)
            if not row:
                return None
            return {"id": row.id, "repo_id": row.repo_id, "proposal": row.proposal, "review": row.review,
                    "applied": [(a["index"], _decode(a)) for a in row.applied]}

    def add_applied(self, pid: str, index: int, undo: dict) -> None:
        with session() as s:
            row = s.get(ProposalRow, pid)
            row.applied = [*row.applied, {"index": index, **_encode(undo)}]

    def remove_applied(self, pid: str, index: int) -> None:
        with session() as s:
            row = s.get(ProposalRow, pid)
            row.applied = [a for a in row.applied if a["index"] != index]


store = ProposalStore()