"""The agent graph.

    START -> [github, for issues] -> planner -> analyst -> coder -> reviewer -> END
                                                    ^                  |
                                                    +-- revise (once) -+

Each agent can also retry itself on invalid output, and several steps can end the run early
(vague task, nothing relevant found, no provider available).
"""
from langgraph.graph import END, START, StateGraph

from app.agents.analyst import analyst
from app.agents.coder import coder
from app.agents.github import github
from app.agents.planner import planner
from app.agents.reviewer import reviewer
from app.graph.state import AgentState


def start_route(state: AgentState) -> str:
    return "github" if state.get("issue_number") and state.get("github_repo") else "planner"


def after_github(state: AgentState) -> str:
    return "end" if state.get("fatal") else "planner"


def after_planner(state: AgentState) -> str:
    if state.get("fatal") or state.get("question"):
        return "end"
    return "analyst" if state.get("plan") else "planner"


def after_analyst(state: AgentState) -> str:
    return "end" if state.get("fatal") or not state.get("hits") else "coder"


def after_coder(state: AgentState) -> str:
    if state.get("fatal"):
        return "end"
    return "reviewer" if state.get("proposal") else "coder"


def after_reviewer(state: AgentState) -> str:
    return "coder" if state.get("revise") else "end"


def build_graph():
    g = StateGraph(AgentState)
    g.add_node("github", github)
    g.add_node("planner", planner)
    g.add_node("analyst", analyst)
    g.add_node("coder", coder)
    g.add_node("reviewer", reviewer)
    g.add_conditional_edges(START, start_route, {"github": "github", "planner": "planner"})
    g.add_conditional_edges("github", after_github, {"planner": "planner", "end": END})
    g.add_conditional_edges("planner", after_planner, {"planner": "planner", "analyst": "analyst", "end": END})
    g.add_conditional_edges("analyst", after_analyst, {"coder": "coder", "end": END})
    g.add_conditional_edges("coder", after_coder, {"coder": "coder", "reviewer": "reviewer", "end": END})
    g.add_conditional_edges("reviewer", after_reviewer, {"coder": "coder", "end": END})
    return g.compile()


graph = build_graph()