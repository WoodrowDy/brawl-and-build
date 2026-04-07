"""Shared fixtures for Phase B tests."""

import pytest
from langchain_core.messages import AIMessage


class FakeLLM:
    """Records invocations and returns a canned AIMessage.

    Used in place of ChatAnthropic so unit/integration tests never hit the
    network. Each instance keeps a list of (messages, kwargs) tuples so tests
    can assert on call count, identity, and message structure.
    """

    def __init__(self, response_text: str = '{"decisions": [], "unresolved": [], "summary": "ok"}'):
        self.response_text = response_text
        self.calls: list[tuple[list, dict]] = []

    def invoke(self, messages, **kwargs) -> AIMessage:
        self.calls.append((messages, kwargs))
        msg = AIMessage(content=self.response_text)
        # Mimic the usage_metadata shape ChatAnthropic returns so cost_tracker
        # does not crash when summing tokens.
        msg.usage_metadata = {
            "input_tokens": 10,
            "output_tokens": 5,
            "total_tokens": 15,
        }
        return msg


@pytest.fixture
def fake_llm() -> FakeLLM:
    return FakeLLM()
