from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.chat import api
from app.api.repos import repos
from app.api.tasks import tasks
from app.api.github import github

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


@app.get("/health")
def health() -> dict:
    return {"status": "ok"}