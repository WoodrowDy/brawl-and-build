"""토론 결과를 Markdown / JSON 파일로 내보내기."""

import json
import os
from datetime import datetime
from core.state import DiscussionState
from models.schemas import DiscussionResult, DiscussionMessage


def state_to_result(state: DiscussionState) -> DiscussionResult:
    """LangGraph 상태를 API 응답 모델로 변환합니다."""
    return DiscussionResult(
        project_description=state["project_description"],
        feature_name=state["feature_name"],
        prompt_used=_build_prompt_summary(state),
        discussion_log=[
            DiscussionMessage(**entry)
            for entry in state.get("discussion_log", [])
        ],
        decisions=state.get("decisions", []),
        unresolved=state.get("unresolved", []),
        summary=state.get("summary", ""),
        total_rounds=state.get("max_rounds", 0),
    )


def export_markdown(result: DiscussionResult, output_dir: str = "output") -> str:
    """토론 결과를 Markdown 파일로 저장합니다."""
    os.makedirs(output_dir, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    filename = f"{output_dir}/discussion_{result.feature_name}_{timestamp}.md"

    lines = [
        f"# 토론 결과: {result.feature_name}",
        f"\n> 프로젝트: {result.project_description}",
        f"> 생성일: {datetime.now().strftime('%Y-%m-%d %H:%M')}",
        f"> 총 라운드: {result.total_rounds}",
        "",
        "---",
        "",
        "## 1. 프롬프트",
        "",
        result.prompt_used,
        "",
        "---",
        "",
        "## 2. 토론 내용",
        "",
    ]

    current_round = None
    for msg in result.discussion_log:
        if msg.round != current_round:
            current_round = msg.round
            lines.append(f"\n### 라운드 {current_round}")
            lines.append("")
        lines.append(f"**[{msg.role}]**")
        lines.append(f"{msg.content}")
        lines.append("")

    lines.extend([
        "---",
        "",
        "## 3. 결과물 (결정 사항)",
        "",
    ])
    for i, decision in enumerate(result.decisions, 1):
        lines.append(f"{i}. {decision}")

    lines.extend([
        "",
        "---",
        "",
        "## 4. 미해결 과제",
        "",
    ])
    for i, item in enumerate(result.unresolved, 1):
        lines.append(f"{i}. {item}")

    lines.extend([
        "",
        "---",
        "",
        "## 5. 요약",
        "",
        result.summary,
    ])

    content = "\n".join(lines)
    with open(filename, "w", encoding="utf-8") as f:
        f.write(content)

    return filename


def export_json(result: DiscussionResult, output_dir: str = "output") -> str:
    """토론 결과를 JSON 파일로 저장합니다."""
    os.makedirs(output_dir, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    filename = f"{output_dir}/discussion_{result.feature_name}_{timestamp}.json"

    with open(filename, "w", encoding="utf-8") as f:
        json.dump(result.model_dump(), f, ensure_ascii=False, indent=2)

    return filename


def _build_prompt_summary(state: DiscussionState) -> str:
    """토론에 사용된 프롬프트 정보를 요약합니다."""
    roles = state.get("role_names", [])
    return (
        f"프로젝트 '{state['project_description']}'에서 "
        f"'{state['feature_name']}' 기능에 대해 "
        f"{', '.join(roles)} 역할이 "
        f"{state.get('max_rounds', 0)} 라운드에 걸쳐 토론을 진행했습니다."
    )
