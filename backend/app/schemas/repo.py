from pydantic import BaseModel


class IndexRequest(BaseModel):
    name: str
    path: str | None = None
    git_url: str | None = None


class SearchRequest(BaseModel):
    query: str
    k: int = 5
