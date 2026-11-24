from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.chat import api
from app.api.repos import repos
from app.api.tasks import tasks
from app.api.github import github
from app.api.proposals import proposals
from app.api.runs import runs

app = FastAPI(title="DevPilot AI")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000"],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(api)
app.include_router(repos)
app.include_router(tasks)
app.include_router(github)
app.include_router(proposals)
app.include_router(runs)


@app.get("/health")
def health() -> dict:
    return {"status": "ok"}