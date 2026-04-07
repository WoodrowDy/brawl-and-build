"""Single factory for ChatAnthropic instances.

This is the only module that should import ChatAnthropic. Every node factory
in the graph receives an instance through dependency injection so the entire
run uses one connection-pooled client.
"""

from langchain_anthropic import ChatAnthropic


def build_llm(model: str = "claude-sonnet-4-20250514", max_tokens: int = 2048) -> ChatAnthropic:
    """Construct a ChatAnthropic client.

    Centralizing construction here lets us tune timeout, retries, and other
    client options in one place. Callers should build one LLM per run and
    reuse it across all nodes.
    """
    return ChatAnthropic(model=model, max_tokens=max_tokens)
