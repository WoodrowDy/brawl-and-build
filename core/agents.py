"""에이전트 노드 생성 - 각 역할별 LLM 호출."""

from langchain_anthropic import ChatAnthropic
from langchain_core.messages import HumanMessage, SystemMessage
from models.schemas import RoleConfig
from core.state import DiscussionState
from core.cost_tracker import get_tracker


def create_agent_node(role: RoleConfig, model: str = "claude-sonnet-4-20250514"):
    """역할별 에이전트 노드를 생성합니다."""

    llm = ChatAnthropic(model=model, max_tokens=2048)

    def agent_node(state: DiscussionState) -> dict:
        discussion_context = _build_discussion_context(state)

        # 이전 기능 토론 컨텍스트 (기능 체이닝)
        prev_ctx = state.get("previous_context", "")
        prev_section = f"\n## 이전 기능 토론에서 결정된 사항\n{prev_ctx}" if prev_ctx else ""

        prompt = f"""## 프로젝트 정보
- 프로젝트: {state["project_description"]}
- 논의 기능: {state["feature_name"]}
{f'- 기능 설명: {state["feature_description"]}' if state.get("feature_description") else ""}
{prev_section}

## 현재 토론 상황
- 라운드: {state["current_round"]}/{state["max_rounds"]}
- 당신의 역할: {role.name} ({role.title})
- 주요 관심 영역: {", ".join(role.focus_areas)}

## 이전 토론 내용
{discussion_context if discussion_context else "(첫 발언입니다. 기능에 대한 초기 의견을 제시하세요.)"}

## 요청
위 맥락을 바탕으로 {role.name} ({role.title}) 관점에서 의견을 제시하세요.
- 이전 기능에서 결정된 사항과 일관성을 유지하세요
- 이전 발언자들의 의견에 대해 동의/반대/보완 의견을 밝히세요
- 당신의 전문 영역에서 놓치고 있는 부분을 지적하세요
- 구체적인 제안이나 대안을 포함하세요
- 300자 이내로 핵심만 간결하게 답변하세요"""

        response = llm.invoke([
            SystemMessage(content=role.system_prompt),
            HumanMessage(content=prompt),
        ])

        # 비용 추적
        get_tracker().track(response, model=model)

        new_entry = {
            "role": role.name,
            "round": state["current_round"],
            "content": response.content,
        }

        updated_log = state.get("discussion_log", []) + [new_entry]

        return {
            "discussion_log": updated_log,
            "messages": [response],
        }

    return agent_node


def create_pm_moderator_node(
    pm_role: RoleConfig,
    mode: str = "question",
    target_role: str = "",
    model: str = "claude-sonnet-4-20250514",
):
    """PM 사회자 노드를 생성합니다.

    mode:
      - "kickoff": 라운드 시작 시 기능 정의 & 각 역할에게 질문 던지기
      - "respond": 멤버 발언 후 PM이 정리/추가질문
      - "wrap_up": 라운드 종합 정리
    """

    llm = ChatAnthropic(model=model, max_tokens=2048)

    def pm_moderator_node(state: DiscussionState) -> dict:
        discussion_context = _build_discussion_context(state)

        if mode == "kickoff":
            instruction = f"""당신은 이번 라운드의 사회자입니다.
라운드 {state["current_round"]}을 시작합니다.

이전 토론 내용을 검토하고:
- 이번 라운드에서 논의할 핵심 쟁점 2-3개를 제시하세요
- 각 팀원(BE, FE, Designer)에게 구체적인 질문을 던지세요
- 이전 라운드의 미해결 사항이 있다면 언급하세요
- 300자 이내로 간결하게 정리하세요"""

        elif mode == "respond":
            instruction = f"""방금 {target_role}의 의견을 들었습니다.
PM 사회자로서:
- {target_role}의 의견에서 핵심 포인트를 짚어주세요
- 동의/반대/보완할 부분을 명확히 하세요
- 다른 팀원의 관점에서 고려할 점을 제기하세요
- 필요하면 추가 질문을 던지세요
- 200자 이내로 간결하게 정리하세요"""

        elif mode == "wrap_up":
            instruction = f"""라운드 {state["current_round"]}의 모든 의견을 들었습니다.
PM 사회자로서 이번 라운드를 종합 정리하세요:
- 합의된 사항을 명시하세요
- 의견이 갈린 쟁점을 정리하세요
- 다음 라운드에서 다뤄야 할 사항을 제시하세요
- 300자 이내로 간결하게 정리하세요"""

        else:
            instruction = "PM으로서 의견을 제시하세요."

        prompt = f"""## 프로젝트 정보
- 프로젝트: {state["project_description"]}
- 논의 기능: {state["feature_name"]}
{f'- 기능 설명: {state["feature_description"]}' if state.get("feature_description") else ""}

## 현재 토론 상황
- 라운드: {state["current_round"]}/{state["max_rounds"]}
- 당신의 역할: PM 사회자 ({pm_role.title})

## 이전 토론 내용
{discussion_context if discussion_context else "(첫 라운드입니다.)"}

## 요청
{instruction}"""

        response = llm.invoke([
            SystemMessage(content=pm_role.system_prompt),
            HumanMessage(content=prompt),
        ])

        get_tracker().track(response, model=model)

        tag = f"PM({mode})"
        if mode == "respond":
            tag = f"PM→{target_role}"

        new_entry = {
            "role": tag,
            "round": state["current_round"],
            "content": response.content,
        }

        updated_log = state.get("discussion_log", []) + [new_entry]

        return {
            "discussion_log": updated_log,
            "messages": [response],
        }

    return pm_moderator_node


def _build_discussion_context(state: DiscussionState) -> tuple[str, int]:
    """Append-only builder for the discussion-context string.

    Returns (cache, new_len) so the calling node can propagate both back into
    LangGraph state. This makes the builder O(n) over the run instead of O(n²)
    because previously-formatted entries are reused verbatim.

    Round headers are emitted whenever the round number changes between the
    last cached entry and the next new entry.
    """
    log = state.get("discussion_log", [])
    cached_len = state.get("context_cache_len", 0) or 0
    cache = state.get("context_cache", "") or ""

    if len(log) <= cached_len:
        return cache, cached_len

    # Determine the round at the tail of the cached portion so we know whether
    # the next new entry needs a fresh round header.
    last_round = log[cached_len - 1]["round"] if cached_len > 0 else None

    new_lines: list[str] = []
    for entry in log[cached_len:]:
        if entry["round"] != last_round:
            last_round = entry["round"]
            new_lines.append(f"\n### 라운드 {last_round}")
        new_lines.append(f"**[{entry['role']}]**: {entry['content']}")

    appended = "\n".join(new_lines)
    cache = f"{cache}\n{appended}" if cache else appended
    return cache, len(log)
