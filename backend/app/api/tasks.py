import asyncio
import json

from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse

from app.database import repo as runs_repo
from app.graph.workflow import graph
from app.rag.store import get_collection
from app.schemas.task import TaskRequest
from app.security.proposals import store

tasks = APIRouter(prefix="/api/tasks")


@tasks.post("/run")
async def run_task(req: TaskRequest) -> StreamingResponse:
    """Run the agent graph and stream each agent's progress as Server-Sent Events.

    Every run is recorded (with its events) so it can be replayed from the History page.
    """
    if get_collection(req.repo_id).count() == 0:
        raise HTTPException(status_code=404, detail="Repository not indexed. Index it first.")

    run_id = await asyncio.to_thread(runs_repo.create_run, req.repo_id, req.task, req.github_repo, req.issue_number)
    queue: asyncio.Queue = asyncio.Queue()
    events: list[dict] = []

    async def emit(event: dict) -> None:
        if event.get("agent") != "system":
            events.append(event)
        await queue.put(event)

    async def runner() -> None:
        try:
            final = await graph.ainvoke(
                {"task": req.task, "repo_id": req.repo_id,
                 **({"github_repo": req.github_repo, "issue_number": req.issue_number}
                    if req.github_repo and req.issue_number else {})},
                config={"configurable": {"emit": emit}},
            )
            proposal = final.get("proposal") or final.get("prev_proposal")  # survive a failed revision
            pid = await asyncio.to_thread(store.save, req.repo_id, proposal, final.get("review")) if proposal else ""
            error = final.get("fatal", "")
            status = "done" if proposal else ("needs_input" if final.get("question") else "error")
            await asyncio.to_thread(runs_repo.finish_run, run_id, status, error, pid or None, events)
            await emit({"agent": "system", "status": "finished",
                        "data": {"ok": bool(proposal), "error": error, "proposal_id": pid, "run_id": run_id,
                                 "question": final.get("question", "")}})
        except asyncio.CancelledError:  # client went away: record it, then let the cancellation continue
            runs_repo.finish_run(run_id, "cancelled", "Stopped before it finished.", None, events)
            raise
        except Exception as e:  # unexpected bug: tell the client instead of hanging
            runs_repo.finish_run(run_id, "error", f"{type(e).__name__}: {e}", None, events)
            await emit({"agent": "system", "status": "finished",
                        "data": {"ok": False, "error": str(e), "run_id": run_id}})
        finally:
            await queue.put(None)

    run = asyncio.create_task(runner())

    async def stream():
        try:
            while (event := await queue.get()) is not None:
                yield f"data: {json.dumps(event)}\n\n"
        finally:
            run.cancel()  # client disconnected or run finished

    return StreamingResponse(
        stream(), media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )