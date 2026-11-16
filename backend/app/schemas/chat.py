from pydantic import BaseModel


class ChatRequest(BaseModel):
    message: str
    system: str = "You are DevPilot, an expert software engineering assistant."
    repo_id: str | None = None  # when set, answers use retrieved code from this repo


class Source(BaseModel):
    path: str
    start_line: int
    end_line: int


class ChatResponse(BaseModel):
    reply: str
    provider: str
    sources: list[Source] = []
