from pydantic import BaseModel, Field


class TaskRequest(BaseModel):
    task: str = Field(min_length=5, max_length=2000)
    repo_id: str