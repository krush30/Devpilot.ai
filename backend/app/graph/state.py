from typing import TypedDict


class AgentState(TypedDict, total=False):
    task: str
    repo_id: str
    github_repo: str  # 'owner/name' when the task starts from a GitHub issue
    issue_number: int
    # planner
    plan: list[str]
    queries: list[str]
    planner_attempts: int
    question: str  # set when the task is too vague: the graph stops and asks the user
    # analyst
    hits: list[dict]
    analysis: str
    # coder
    proposal: dict
    coder_attempts: int
    # control flow
    error: str  # transient: fed back to the agent on retry
    fatal: str  # permanent: stops the graph