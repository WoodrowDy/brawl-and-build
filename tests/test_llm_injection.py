"""Verify the LLM factory and injection wiring."""

from pathlib import Path

from langchain_anthropic import ChatAnthropic
from core.graph import run_discussion
from core.llm import build_llm
from tests.conftest import FakeLLM


def test_build_llm_returns_chat_anthropic():
    llm = build_llm(model="claude-haiku-4-5-20251001", max_tokens=128)
    assert isinstance(llm, ChatAnthropic)


def test_build_llm_respects_kwargs():
    llm = build_llm(model="claude-haiku-4-5-20251001", max_tokens=512)
    # ChatAnthropic stores model on .model
    assert llm.model == "claude-haiku-4-5-20251001"


def test_single_llm_instance_reaches_every_node():
    """Every node invocation must use the same injected LLM object."""
    fake = FakeLLM(response_text='{"decisions": ["d1"], "unresolved": [], "summary": "s"}')
    summarizer_fake = FakeLLM(response_text='{"decisions": ["d1"], "unresolved": [], "summary": "s"}')

    run_discussion(
        project_description="test project",
        feature_name="test feature",
        max_rounds=1,
        enable_build=False,
        llm=fake,
        summarizer_llm=summarizer_fake,
    )

    # 1 round = pm_kickoff + 3*(agent + pm_respond) + pm_wrap_up = 8 calls on `fake`
    assert len(fake.calls) == 8, f"expected 8 LLM calls, got {len(fake.calls)}"
    # summarizer fake should have exactly 1 call
    assert len(summarizer_fake.calls) == 1


def test_chat_anthropic_only_imported_in_core_llm():
    """Static check: only core/llm.py should import ChatAnthropic."""
    repo = Path(__file__).resolve().parents[1]
    offenders = []
    for path in list(repo.glob("core/*.py")) + [repo / "cli.py"]:
        if path.name == "llm.py":
            continue
        source = path.read_text(encoding="utf-8")
        if "ChatAnthropic" in source:
            offenders.append(str(path.relative_to(repo)))
    assert offenders == [], f"ChatAnthropic must only live in core/llm.py, found in: {offenders}"
