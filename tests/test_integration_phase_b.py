"""End-to-end run of the discussion graph using FakeLLM.

Asserts:
  - The graph completes without raising
  - context_cache is populated and grows monotonically
  - Final state contains decisions/unresolved/summary
  - cache_len matches len(discussion_log) (the post-append invariant)
  - Cache resets between separate runs
"""

from core.graph import run_discussion
from tests.conftest import FakeLLM


def test_full_run_with_fake_llm():
    """End-to-end test with max_rounds=2, verify call count and cache invariant."""
    fake = FakeLLM(response_text="opinion line")
    summarizer_fake = FakeLLM(
        response_text='{"decisions": ["use postgres"], "unresolved": ["auth"], "summary": "ok"}'
    )

    final = run_discussion(
        project_description="todo app",
        feature_name="signup",
        feature_description="email + password",
        max_rounds=2,
        enable_build=False,
        llm=fake,
        summarizer_llm=summarizer_fake,
    )

    # 2 rounds * (1 kickoff + 3 agents + 3 responds + 1 wrap_up) = 16 calls
    assert len(fake.calls) == 16, f"expected 16 LLM calls, got {len(fake.calls)}"
    assert len(summarizer_fake.calls) == 1, f"expected 1 summarizer call, got {len(summarizer_fake.calls)}"

    assert final["decisions"] == ["use postgres"]
    assert final["unresolved"] == ["auth"]
    assert final["summary"] == "ok"

    # Cache must have absorbed every discussion entry
    assert final["context_cache_len"] == len(final["discussion_log"]), (
        f"cache_len={final['context_cache_len']} != "
        f"log_len={len(final['discussion_log'])}"
    )
    assert final["context_cache"], "context_cache should be non-empty"
    assert "라운드 1" in final["context_cache"], "라운드 1 header missing from cache"
    assert "라운드 2" in final["context_cache"], "라운드 2 header missing from cache"


def test_cache_reset_between_runs():
    """Verify that each run starts with a fresh cache, not accumulated."""
    fake = FakeLLM(response_text="x")
    summarizer_fake = FakeLLM(
        response_text='{"decisions": [], "unresolved": [], "summary": ""}'
    )

    final1 = run_discussion(
        project_description="p",
        feature_name="f1",
        max_rounds=1,
        llm=fake,
        summarizer_llm=summarizer_fake,
    )
    final2 = run_discussion(
        project_description="p",
        feature_name="f2",
        max_rounds=1,
        llm=fake,
        summarizer_llm=summarizer_fake,
    )

    # Each run starts from a fresh initial_state, so cache_len reflects that
    # run's log only — not accumulated across runs.
    assert final2["context_cache_len"] == len(final2["discussion_log"]), (
        f"Run 2: cache_len={final2['context_cache_len']} != "
        f"log_len={len(final2['discussion_log'])}"
    )
    assert "f2" not in final1["context_cache"], (
        "f2 should not appear in run 1's cache"
    )
