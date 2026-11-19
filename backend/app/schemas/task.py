from pydantic import BaseModel, Field, model_validator

GITHUB_REPO = r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$"


class TaskRequest(BaseModel):
    task: str = Field(default="", max_length=2000)
    repo_id: str
    github_repo: str | None = Field(default=None, pattern=GITHUB_REPO)
    issue_number: int | None = Field(default=None, ge=1)

    @model_validator(mode="after")
    def need_task_or_issue(self):
        has_issue = bool(self.github_repo and self.issue_number)
        if not has_issue and len(self.task.strip()) < 5:
            raise ValueError("Provide a task (5+ characters) or a GitHub repo and issue number")
        return self