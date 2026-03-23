"""API 호출 비용 추적기 - Anthropic 모델용."""

from dataclasses import dataclass, field
from contextlib import contextmanager

# Anthropic 모델별 가격 (USD per 1M tokens, 2025년 기준)
MODEL_PRICING = {
    "claude-sonnet-4-20250514": {"input": 3.0, "output": 15.0},
    "claude-haiku-4-5-20251001": {"input": 0.80, "output": 4.0},
    "claude-opus-4-20250514": {"input": 15.0, "output": 75.0},
}


@dataclass
class CostTracker:
    """API 호출 토큰 및 비용을 누적 추적합니다."""

    total_tokens: int = 0
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_cost: float = 0.0
    call_count: int = 0
    call_details: list = field(default_factory=list)

    def track(self, response, model: str = "claude-sonnet-4-20250514"):
        """LLM 응답에서 토큰 사용량을 추출하여 누적합니다."""
        usage = getattr(response, "usage_metadata", None)
        if usage is None:
            # response_metadata에서 시도
            meta = getattr(response, "response_metadata", {})
            usage_raw = meta.get("usage", {})
            input_tokens = usage_raw.get("input_tokens", 0)
            output_tokens = usage_raw.get("output_tokens", 0)
        else:
            input_tokens = usage.get("input_tokens", 0)
            output_tokens = usage.get("output_tokens", 0)

        self.prompt_tokens += input_tokens
        self.completion_tokens += output_tokens
        self.total_tokens += input_tokens + output_tokens
        self.call_count += 1

        # 비용 계산
        pricing = MODEL_PRICING.get(model, MODEL_PRICING["claude-sonnet-4-20250514"])
        input_cost = (input_tokens / 1_000_000) * pricing["input"]
        output_cost = (output_tokens / 1_000_000) * pricing["output"]
        call_cost = input_cost + output_cost
        self.total_cost += call_cost

        self.call_details.append({
            "call_number": self.call_count,
            "model": model,
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
            "cost": round(call_cost, 6),
        })

    def summary(self) -> str:
        """비용 요약을 문자열로 반환합니다."""
        lines = [
            "",
            "=" * 50,
            "💰 API 사용량 & 비용 리포트",
            "=" * 50,
            f"  총 API 호출 횟수:        {self.call_count}회",
            f"  총 사용 토큰:            {self.total_tokens:,}",
            f"  ├─ 프롬프트(입력) 토큰:  {self.prompt_tokens:,}",
            f"  └─ 응답(출력) 토큰:      {self.completion_tokens:,}",
            f"  총 비용(USD):            ${self.total_cost:.4f}",
            f"  총 비용(KRW):            ₩{self.total_cost * 1_450:.0f} (약 환율 1,450원)",
            "=" * 50,
        ]
        return "\n".join(lines)

    def detail_summary(self) -> str:
        """호출별 상세 비용을 문자열로 반환합니다."""
        lines = ["\n📊 호출별 상세:"]
        for d in self.call_details:
            lines.append(
                f"  [{d['call_number']:2d}] {d['model']} | "
                f"in: {d['input_tokens']:,} / out: {d['output_tokens']:,} | "
                f"${d['cost']:.4f}"
            )
        return "\n".join(lines)

    def to_dict(self) -> dict:
        """JSON 직렬화용 딕셔너리를 반환합니다."""
        return {
            "total_tokens": self.total_tokens,
            "prompt_tokens": self.prompt_tokens,
            "completion_tokens": self.completion_tokens,
            "total_cost_usd": round(self.total_cost, 4),
            "total_cost_krw": round(self.total_cost * 1_450),
            "call_count": self.call_count,
            "call_details": self.call_details,
        }


# 글로벌 트래커 인스턴스
_global_tracker: CostTracker | None = None


def get_tracker() -> CostTracker:
    """현재 활성화된 트래커를 반환합니다."""
    global _global_tracker
    if _global_tracker is None:
        _global_tracker = CostTracker()
    return _global_tracker


def reset_tracker():
    """트래커를 초기화합니다."""
    global _global_tracker
    _global_tracker = CostTracker()


@contextmanager
def track_cost():
    """비용 추적 컨텍스트 매니저. OpenAI의 get_openai_callback()과 유사합니다.

    사용법:
        with track_cost() as tracker:
            result = run_discussion(...)
            print(tracker.summary())
    """
    tracker = CostTracker()
    global _global_tracker
    old_tracker = _global_tracker
    _global_tracker = tracker
    try:
        yield tracker
    finally:
        _global_tracker = old_tracker
