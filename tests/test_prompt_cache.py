"""Verify cache_control markers on system blocks at every LLM call site."""

from langchain_core.messages import SystemMessage, HumanMessage

from core.graph import run_discussion
from tests.conftest import FakeLLM


def _system_block_list(call):
    messages, _ = call
    sys_msg = next(m for m in messages if isinstance(m, SystemMessage))
    assert isinstance(sys_msg.content, list), (
        "SystemMessage.content must be a list of cache-marked blocks"
    )
    return sys_msg.content


def _human_block(call):
    messages, _ = call
    return next(m for m in messages if isinstance(m, HumanMessage))


def test_every_agent_call_has_cached_system_blocks():
    fake = FakeLLM()
    summarizer_fake = FakeLLM()
    run_discussion(
        project_description="p",
        feature_name="f",
        max_rounds=1,
        llm=fake,
        summarizer_llm=summarizer_fake,
    )

    for call in fake.calls:
        blocks = _system_block_list(call)
        assert len(blocks) == 2, "agent/PM nodes should have role + project meta blocks"
        for block in blocks:
            assert block["type"] == "text"
            assert block["cache_control"] == {"type": "ephemeral"}


def test_summarizer_has_cached_system_block():
    fake = FakeLLM()
    summarizer_fake = FakeLLM()
    run_discussion(
        project_description="p",
        feature_name="f",
        max_rounds=1,
        llm=fake,
        summarizer_llm=summarizer_fake,
    )

    blocks = _system_block_list(summarizer_fake.calls[0])
    assert len(blocks) == 1
    assert blocks[0]["cache_control"] == {"type": "ephemeral"}


def test_human_message_is_not_cache_marked():
    fake = FakeLLM()
    summarizer_fake = FakeLLM()
    run_discussion(
        project_description="p",
        feature_name="f",
        max_rounds=1,
        llm=fake,
        summarizer_llm=summarizer_fake,
    )

    for call in fake.calls:
        human = _human_block(call)
        # HumanMessage stays as a plain string — never cached.
        assert isinstance(human.content, str)
