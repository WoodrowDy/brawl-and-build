"""Verify the LLM factory and injection wiring."""

from langchain_anthropic import ChatAnthropic
from core.llm import build_llm


def test_build_llm_returns_chat_anthropic():
    llm = build_llm(model="claude-haiku-4-5-20251001", max_tokens=128)
    assert isinstance(llm, ChatAnthropic)


def test_build_llm_respects_kwargs():
    llm = build_llm(model="claude-haiku-4-5-20251001", max_tokens=512)
    # ChatAnthropic stores model on .model
    assert llm.model == "claude-haiku-4-5-20251001"
