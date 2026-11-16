"""The agent graph:  planner -> analyst -> coder, with retry loops and early exits.

    START -> planner --(valid plan)--> analyst --(code found)--> coder --(proposal)--> END
                ^  \\--(invalid, retry)-/            \\--(nothing found)--> END       |
                |                                                                  |
                +------------------ coder retries itself on invalid output <-------+
"""
from langgraph.graph import END, START, StateGraph

from app.agents.analyst import analyst
from app.agents.coder import coder
from app.agents.planner import planner
from app.graph.state import AgentState


def after_planner(state: AgentState) -> str:
    if state.get("fatal"):
        return "end"
    return "analyst" if state.get("plan") else "planner"


def after_analyst(state: AgentState) -> str:
    return "end" if state.get("fatal") or not state.get("hits") else "coder"


def after_coder(state: AgentState) -> str:
    if state.get("fatal") or state.get("proposal"):
        return "end"
    return "coder"


def build_graph():
    g = StateGraph(AgentState)
    g.add_node("planner", planner)
    g.add_node("analyst", analyst)
    g.add_node("coder", coder)
    g.add_edge(START, "planner")
    g.add_conditional_edges("planner", after_planner, {"planner": "planner", "analyst": "analyst", "end": END})
    g.add_conditional_edges("analyst", after_analyst, {"coder": "coder", "end": END})
    g.add_conditional_edges("coder", after_coder, {"coder": "coder", "end": END})
    return g.compile()


graph = build_graph()