"""Unit tests for the incremental discussion-context builder."""

from core.agents import _build_discussion_context


def _state(log, cache="", cache_len=0):
    return {
        "discussion_log": log,
        "context_cache": cache,
        "context_cache_len": cache_len,
    }


def test_empty_log_returns_empty_cache():
    cache, new_len = _build_discussion_context(_state([]))
    assert cache == ""
    assert new_len == 0


def test_first_entry_builds_cache():
    log = [{"role": "BE", "round": 1, "content": "use postgres"}]
    cache, new_len = _build_discussion_context(_state(log))
    assert "라운드 1" in cache
    assert "[BE]" in cache
    assert "use postgres" in cache
    assert new_len == 1


def test_second_call_appends_only_new_entries():
    log1 = [{"role": "BE", "round": 1, "content": "use postgres"}]
    cache1, len1 = _build_discussion_context(_state(log1))

    log2 = log1 + [{"role": "FE", "round": 1, "content": "use react"}]
    cache2, len2 = _build_discussion_context(_state(log2, cache=cache1, cache_len=len1))

    assert cache2.startswith(cache1)  # previous portion preserved byte-for-byte
    assert "use react" in cache2
    assert len2 == 2


def test_idempotent_when_log_unchanged():
    log = [{"role": "BE", "round": 1, "content": "x"}]
    cache1, len1 = _build_discussion_context(_state(log))
    cache2, len2 = _build_discussion_context(_state(log, cache=cache1, cache_len=len1))
    assert cache1 == cache2
    assert len1 == len2 == 1


def test_round_header_appears_when_round_changes():
    log = [
        {"role": "BE", "round": 1, "content": "a"},
        {"role": "FE", "round": 2, "content": "b"},
    ]
    cache, _ = _build_discussion_context(_state(log))
    assert "라운드 1" in cache
    assert "라운드 2" in cache
