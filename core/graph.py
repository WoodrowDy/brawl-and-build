"""LangGraph 토론 그래프 구성 - PM 허브형 + Build 페이즈."""

from langgraph.graph import StateGraph, END
from models.schemas import RoleConfig
from core.state import DiscussionState
from core.agents import create_agent_node, create_pm_moderator_node
from core.summarizer import create_summarizer_node
from core.code_generator import create_build_node
from core.llm import build_llm


def build_discussion_graph(
    roles: list[RoleConfig],
    llm,
    summarizer_llm,
    max_rounds: int = 2,
    model: str = "claude-sonnet-4-20250514",
    summarizer_model: str = "claude-haiku-4-5-20251001",
    enable_build: bool = False,
):
    """Build the PM-hub discussion graph + optional build phase.

    `llm` is reused by every agent/PM/build node. `summarizer_llm` is a
    separate (typically smaller/cheaper) instance because the summarizer uses
    a different default model.
    """

    graph = StateGraph(DiscussionState)

    pm_role = roles[0]
    member_roles = [r for r in roles if r.name != pm_role.name]

    graph.add_node(
        "pm_kickoff",
        create_pm_moderator_node(pm_role, llm, mode="kickoff", model=model),
    )

    for member in member_roles:
        graph.add_node(
            f"agent_{member.name}",
            create_agent_node(member, llm, model=model),
        )
        graph.add_node(
            f"pm_respond_{member.name}",
            create_pm_moderator_node(
                pm_role, llm, mode="respond", target_role=member.name, model=model
            ),
        )

    graph.add_node(
        "pm_wrap_up",
        create_pm_moderator_node(pm_role, llm, mode="wrap_up", model=model),
    )

    def increment_round(state: DiscussionState) -> dict:
        return {"current_round": state["current_round"] + 1}

    graph.add_node("increment_round", increment_round)
    graph.add_node("summarizer", create_summarizer_node(summarizer_llm, model=summarizer_model))

    graph.set_entry_point("pm_kickoff")
    graph.add_edge("pm_kickoff", f"agent_{member_roles[0].name}")

    for i, member in enumerate(member_roles):
        graph.add_edge(f"agent_{member.name}", f"pm_respond_{member.name}")
        if i < len(member_roles) - 1:
            next_member = member_roles[i + 1]
            graph.add_edge(f"pm_respond_{member.name}", f"agent_{next_member.name}")
        else:
            graph.add_edge(f"pm_respond_{member.name}", "pm_wrap_up")

    graph.add_edge("pm_wrap_up", "increment_round")

    def should_continue(state: DiscussionState) -> str:
        if state["current_round"] > state["max_rounds"]:
            return "summarizer"
        return "pm_kickoff"

    graph.add_conditional_edges("increment_round", should_continue)

    if enable_build:
        graph.add_node("build_api_spec", create_build_node("api_spec", llm, model=model))
        graph.add_node("build_shared", create_build_node("shared", llm, model=model))
        graph.add_node("build_be", create_build_node("be", llm, model=model))
        graph.add_node("build_fe", create_build_node("fe", llm, model=model))

        graph.add_edge("summarizer", "build_api_spec")
        graph.add_edge("build_api_spec", "build_shared")
        graph.add_edge("build_shared", "build_be")
        graph.add_edge("build_be", "build_fe")
        graph.add_edge("build_fe", END)
    else:
        graph.add_edge("summarizer", END)

    return graph.compile()


def run_discussion(
    project_description: str,
    feature_name: str,
    feature_description: str = "",
    roles: list[RoleConfig] | None = None,
    max_rounds: int = 2,
    model: str = "claude-sonnet-4-20250514",
    summarizer_model: str = "claude-haiku-4-5-20251001",
    enable_build: bool = False,
    previous_context: str = "",
    llm=None,
    summarizer_llm=None,
) -> DiscussionState:
    """Run a discussion. Builds one LLM per role group and reuses across nodes.

    Tests can pass in `llm` / `summarizer_llm` to inject FakeLLMs.
    """
    from config.roles import DEFAULT_ROLES

    if roles is None:
        roles = DEFAULT_ROLES

    if llm is None:
        llm = build_llm(model=model, max_tokens=2048)
    if summarizer_llm is None:
        summarizer_llm = build_llm(model=summarizer_model, max_tokens=2048)

    app = build_discussion_graph(
        roles,
        llm=llm,
        summarizer_llm=summarizer_llm,
        max_rounds=max_rounds,
        model=model,
        summarizer_model=summarizer_model,
        enable_build=enable_build,
    )

    initial_state: DiscussionState = {
        "project_description": project_description,
        "feature_name": feature_name,
        "feature_description": feature_description,
        "current_round": 1,
        "max_rounds": max_rounds,
        "current_role_index": 0,
        "role_names": [r.name for r in roles],
        "discussion_log": [],
        "messages": [],
        "decisions": [],
        "unresolved": [],
        "summary": "",
        "previous_context": previous_context,
        "build_enabled": enable_build,
        "build_outputs": [],
        # Phase B: per-run cache, reset every run
        "context_cache": "",
        "context_cache_len": 0,
    }

    final_state = app.invoke(initial_state)
    return final_state
