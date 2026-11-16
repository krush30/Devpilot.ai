from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.chat import api
from app.api.repos import repos

app = FastAPI(title="DevPilot AI")
app.add_middleware(
    CORSMiddleware, allow_origins=["http://localhost:3000"],
    allow_methods=["*"], allow_headers=["*"],
)
app.include_router(api)
app.include_router(repos)


@app.get("/health")
def health() -> dict:
    return {"status": "ok"}
