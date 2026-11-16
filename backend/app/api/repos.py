import subprocess

from fastapi import APIRouter, HTTPException

from app.rag.ingestion import index_repo
from app.rag.retrieval import search
from app.rag.store import list_repos
from app.schemas.repo import IndexRequest, SearchRequest

repos = APIRouter(prefix="/api/repos")


@repos.post("/index")
def index(req: IndexRequest) -> dict:
    # Plain `def`: FastAPI runs it in a worker thread, so slow embedding doesn't block the server.
    try:
        return index_repo(req.name, req.path, req.git_url)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except subprocess.CalledProcessError as e:
        raise HTTPException(status_code=400, detail=f"git clone failed: {e.stderr.decode()[:300]}")


@repos.get("")
def list_all() -> list[dict]:
    return list_repos()


@repos.post("/{repo_id}/search")
def search_repo(repo_id: str, req: SearchRequest) -> list[dict]:
    return search(repo_id, req.query, req.k)
