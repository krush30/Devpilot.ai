from fastapi import APIRouter, HTTPException, Query

from app.database import repo

runs = APIRouter(prefix="/api/runs")


@runs.get("")
def list_all(limit: int = Query(30, ge=1, le=100), repo_id: str | None = None) -> list[dict]:
    return repo.list_runs(limit, repo_id)


@runs.get("/{run_id}")
def detail(run_id: str) -> dict:
    run = repo.get_run(run_id)
    if not run:
        raise HTTPException(status_code=404, detail="Run not found.")
    return run


@runs.delete("/{run_id}")
def remove(run_id: str) -> dict:
    if not repo.delete_run(run_id):
        raise HTTPException(status_code=404, detail="Run not found.")
    return {"deleted": run_id}