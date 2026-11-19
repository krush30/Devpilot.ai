"""Server-side store of agent proposals.

The approval endpoint applies exactly what the agents produced. The browser only says
"apply proposal X, changes 0 and 2", it never sends code to write. In memory for now;
Week 6 moves this to PostgreSQL.
"""
import secrets
import threading
import time

TTL_SECONDS = 2 * 60 * 60
MAX_PROPOSALS = 50


class ProposalStore:
    def __init__(self) -> None:
        self._items: dict[str, dict] = {}
        self.lock = threading.RLock()

    def save(self, repo_id: str, proposal: dict, review: dict | None = None) -> str:
        with self.lock:
            now = time.time()
            for pid in [k for k, v in self._items.items() if now - v["created"] > TTL_SECONDS]:
                del self._items[pid]
            while len(self._items) >= MAX_PROPOSALS:
                del self._items[min(self._items, key=lambda k: self._items[k]["created"])]
            pid = secrets.token_urlsafe(9)
            self._items[pid] = {"id": pid, "repo_id": repo_id, "proposal": proposal, "review": review,
                                "created": now, "applied": []}  # applied: [(change_index, undo_info)]
            return pid

    def get(self, pid: str) -> dict | None:
        with self.lock:
            rec = self._items.get(pid)
            return rec if rec and time.time() - rec["created"] <= TTL_SECONDS else None


store = ProposalStore()