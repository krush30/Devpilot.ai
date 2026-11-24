"""The approval gate. Nothing is written to disk except through POST /apply."""
from pathlib import Path

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from app.rag.store import get_root
from app.security.proposals import store
from app.tools.apply import apply_change, undo_change

proposals = APIRouter(prefix="/api/proposals")

NO_ROOT = ("This repository was not indexed from a local folder (or was indexed before Week 5), "
           "so DevPilot doesn't know where its files are. Re-index it from a local folder path.")


class ApplyRequest(BaseModel):
    change_indexes: list[int] = Field(min_length=1, max_length=10)
    dry_run: bool = False


def _record(pid: str) -> dict:
    rec = store.get(pid)
    if not rec:
        raise HTTPException(status_code=404, detail="Proposal not found. Run the agents again.")
    return rec


def _root(rec: dict) -> Path | None:
    raw = get_root(rec["repo_id"])
    return Path(raw) if raw and Path(raw).is_dir() else None


@proposals.get("/{pid}")
def view(pid: str) -> dict:
    rec = _record(pid)
    root = _root(rec)
    applied = {i for i, _ in rec["applied"]}
    changes = []
    for i, c in enumerate(rec["proposal"]["changes"]):
        reason = ("" if root else "repository folder unknown") or (
            "Python syntax error" if c["syntax"] == "error" else "" if c["verified"] else "original code not found")
        changes.append({"index": i, "path": c["path"], "action": c["action"], "line": c["line"],
                        "explanation": c["explanation"], "diff": c["diff"], "verified": c["verified"],
                        "syntax": c["syntax"], "eligible": not reason, "ineligible_reason": reason,
                        "applied": i in applied})
    return {"id": pid, "repo_id": rec["repo_id"], "root": str(root) if root else None,
            "can_apply": root is not None, "cannot_apply_reason": "" if root else NO_ROOT,
            "summary": rec["proposal"]["summary"], "review": rec["review"], "changes": changes}


@proposals.post("/{pid}/apply")
def apply(pid: str, body: ApplyRequest) -> dict:
    rec = _record(pid)
    root = _root(rec)
    if root is None:
        raise HTTPException(status_code=409, detail=NO_ROOT)
    changes, results = rec["proposal"]["changes"], []
    with store.lock:
        done = {i for i, _ in rec["applied"]}
        for idx in sorted(set(body.change_indexes)):
            if not 0 <= idx < len(changes):
                results.append({"index": idx, "path": "", "status": "skipped", "detail": "no such change"})
                continue
            path = changes[idx]["path"]
            if idx in done and not body.dry_run:
                results.append({"index": idx, "path": path, "status": "skipped", "detail": "already applied"})
                continue
            out = apply_change(root, changes[idx], dry_run=body.dry_run)
            if out.status == "applied":
                store.add_applied(pid, idx, out.undo)
            results.append({"index": idx, "path": path, "status": out.status, "detail": out.detail})
    return {"results": results, "root": str(root)}


@proposals.post("/{pid}/undo")
def undo(pid: str) -> dict:
    rec = _record(pid)
    results = []
    with store.lock:
        for idx, info in reversed(rec["applied"]):  # newest first, so stacked edits unwind cleanly
            out = undo_change(info)
            if out.status == "undone":
                store.remove_applied(pid, idx)
            results.append({"index": idx, "path": rec["proposal"]["changes"][idx]["path"],
                            "status": out.status, "detail": out.detail})
    return {"results": results}