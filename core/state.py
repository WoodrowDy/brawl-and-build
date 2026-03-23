"""LangGraph 상태 정의."""

from typing import TypedDict, Annotated
from langgraph.graph import add_messages
from langchain_core.messages import BaseMessage


class DiscussionState(TypedDict):
    """토론 전체 상태를 관리하는 TypedDict"""

    # 프로젝트 정보
    project_description: str
    feature_name: str
    feature_description: str

    # 토론 진행 상태
    current_round: int
    max_rounds: int
    current_role_index: int
    role_names: list[str]

    # 토론 내용 누적
    discussion_log: list[dict]  # [{role, round, content}, ...]

    # LangGraph 메시지 (내부용)
    messages: Annotated[list[BaseMessage], add_messages]

    # 결과물
    decisions: list[str]
    unresolved: list[str]
    summary: str

    # 이전 토론 컨텍스트 (기능 체이닝)
    previous_context: str

    # Build 페이즈
    build_enabled: bool
    build_outputs: list[dict]  # [{role, content}, ...]
