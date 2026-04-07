"""토론 결과 정리 에이전트."""

import json
from langchain_core.messages import HumanMessage, SystemMessage
from core.state import DiscussionState
from core.cost_tracker import get_tracker


SUMMARIZER_SYSTEM_PROMPT = """당신은 프로젝트 토론 내용을 정리하는 전문가입니다.
토론 내용을 분석하여 다음 4가지를 도출하세요:

1. **결정 사항 (decisions)**: 팀원들이 합의한 내용
2. **미해결 과제 (unresolved)**: 의견이 갈리거나 추가 논의가 필요한 사항
3. **요약 (summary)**: 전체 토론의 핵심 내용 요약

반드시 아래 JSON 형식으로만 응답하세요:
```json
{
  "decisions": ["결정사항1", "결정사항2", ...],
  "unresolved": ["미해결1", "미해결2", ...],
  "summary": "전체 토론 요약 텍스트"
}
```"""


def create_summarizer_node(llm, model: str = "claude-haiku-4-5-20251001"):
    """토론 결과를 정리하는 요약 노드를 생성합니다."""

    def summarizer_node(state: DiscussionState) -> dict:
        discussion_text = _format_discussion_log(state)

        prompt = f"""## 프로젝트: {state["project_description"]}
## 논의 기능: {state["feature_name"]}

## 전체 토론 내용:
{discussion_text}

위 토론 내용을 분석하여 결정사항, 미해결과제, 요약을 JSON 형식으로 정리하세요."""

        system_blocks = [
            {
                "type": "text",
                "text": SUMMARIZER_SYSTEM_PROMPT,
                "cache_control": {"type": "ephemeral"},
            },
        ]

        response = llm.invoke([
            SystemMessage(content=system_blocks),
            HumanMessage(content=prompt),
        ])

        # 비용 추적
        get_tracker().track(response, model=model)

        # JSON 파싱
        result = _parse_summary_response(response.content)

        return {
            "decisions": result.get("decisions", []),
            "unresolved": result.get("unresolved", []),
            "summary": result.get("summary", "요약 생성 실패"),
            "messages": [response],
        }

    return summarizer_node


def _format_discussion_log(state: DiscussionState) -> str:
    """토론 로그를 정리된 텍스트로 변환합니다."""
    lines = []
    current_round = None

    for entry in state.get("discussion_log", []):
        if entry["round"] != current_round:
            current_round = entry["round"]
            lines.append(f"\n=== 라운드 {current_round} ===")
        lines.append(f"[{entry['role']}]: {entry['content']}\n")

    return "\n".join(lines)


def _parse_summary_response(content: str) -> dict:
    """LLM 응답에서 JSON을 추출합니다."""
    try:
        # ```json ... ``` 블록 추출 시도
        if "```json" in content:
            json_str = content.split("```json")[1].split("```")[0].strip()
        elif "```" in content:
            json_str = content.split("```")[1].split("```")[0].strip()
        else:
            json_str = content.strip()

        return json.loads(json_str)
    except (json.JSONDecodeError, IndexError):
        return {
            "decisions": [],
            "unresolved": ["요약 파싱 실패 - 원본 응답을 확인하세요"],
            "summary": content,
        }
