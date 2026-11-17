import asyncio
import json

from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse

from app.graph.workflow import graph
from app.rag.store import get_collection
from app.schemas.task import TaskRequest

tasks = APIRouter(prefix="/api/tasks")


@tasks.post("/run")
async def run_task(req: TaskRequest) -> StreamingResponse:
    """Run the agent graph and stream each agent's progress as Server-Sent Events."""
    if get_collection(req.repo_id).count() == 0:
        raise HTTPException(status_code=404, detail="Repository not indexed. Index it first.")

    queue: asyncio.Queue = asyncio.Queue()

    async def emit(event: dict) -> None:
        await queue.put(event)

    async def runner() -> None:
        try:
            final = await graph.ainvoke(
                {"task": req.task, "repo_id": req.repo_id},
                config={"configurable": {"emit": emit}},
            )
            await emit({"agent": "system", "status": "finished",
                        "data": {"ok": bool(final.get("proposal")), "error": final.get("fatal", ""),
                                 "question": final.get("question", "")}})
        except Exception as e:  # unexpected bug: tell the client instead of hanging
            await emit({"agent": "system", "status": "finished", "data": {"ok": False, "error": str(e)}})
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