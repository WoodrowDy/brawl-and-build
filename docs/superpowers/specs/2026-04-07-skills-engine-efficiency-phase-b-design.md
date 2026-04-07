# Brawl & Build — Skills/Engine Efficiency (Phase B) Design

**Date**: 2026-04-07
**Status**: Approved design, ready for implementation plan
**Scope**: Phase B (Quick Wins). Phase C (parallelization) is deferred to a separate spec.

## 1. Goal & Scope

Reduce token cost and latency by 30-50% **without changing** the discussion flow, LangGraph topology, persona behavior, or CLI UX.

**In scope**
1. LLM dependency injection (singleton via factory)
2. State-based incremental discussion-context cache
3. Anthropic prompt caching for static prefix (role system + project meta)

**Out of scope (Phase C)**
- Intra-round parallelization of BE/FE/Designer
- Parallel build phase (api_spec / shared / be / fe)
- LangGraph topology changes

## 2. Background — Audit Findings

Top inefficiencies identified in current code:

| # | Issue | Location |
|---|---|---|
| 1 | `ChatAnthropic` instantiated 7+ times per run (no singleton) | `core/agents.py:13,82`, `core/summarizer.py:30`, `core/code_generator.py:127` |
| 2 | `_build_discussion_context()` rebuilds full log every call (O(n²)) | `core/agents.py:16,85,159-173` |
| 5 | No Anthropic prompt caching (`cache_control`) | `core/agents.py:44-46`, `core/code_generator.py:164-166` |

Phase B addresses #1, #2, #5. Phase C will address #3 (sequential build) and intra-round parallelism.

## 3. Architecture Changes

### New module
- **`core/llm.py`** — exposes `build_llm(config) -> ChatAnthropic`. Single entry point for LLM construction. Centralizes model name, temperature, timeout, and any future client config.

### Modified modules
- **`cli.py`** — at startup, call `llm = build_llm(...)` once and pass into `build_graph(llm)`.
- **`core/graph.py`** — `build_graph(llm)` accepts the LLM and forwards it to all node factories.
- **`core/agents.py`** — `create_agent_node(role, llm)` and `create_pm_moderator_node(llm)` accept `llm` instead of constructing `ChatAnthropic` internally.
- **`core/summarizer.py`** — `summarize(state, llm)` takes `llm` as a parameter.
- **`core/code_generator.py`** — build node factories accept `llm`.
- **`core/state.py`** — `DiscussionState` gains two fields:
  - `context_cache: str` (default `""`)
  - `context_cache_len: int` (default `0`)

### Invariants (unchanged)
- LangGraph topology and node order
- PM-hub discussion flow
- Persona definitions and prompts
- CLI UX and outputs
- Pydantic schemas in `models/`

## 4. Incremental Context Cache

### Current behavior (`core/agents.py:159-173`)
```python
def _build_discussion_context(state):
    parts = []
    for entry in state["discussion_log"]:
        parts.append(f"[{entry['role']}] {entry['message']}")
    return "\n".join(parts)
```
Rebuilds the full string every call → O(n²) accumulated cost across a round.

### New behavior
```python
def _build_discussion_context(state):
    log = state["discussion_log"]
    cached_len = state.get("context_cache_len", 0)
    cache = state.get("context_cache", "")

    if len(log) > cached_len:
        new_parts = [f"[{e['role']}] {e['message']}" for e in log[cached_len:]]
        cache = (cache + "\n" + "\n".join(new_parts)).strip()

    return cache, len(log)
```

Each agent/PM node includes the updated `context_cache` and `context_cache_len` in its returned state dict, so LangGraph propagates them through the graph naturally — no hidden global state.

**Cache reset**: `cli.py` clears the cache fields when starting a new feature/round so previous-round content does not leak.

**Complexity**: O(n²) → O(n).

**Why state-based**: External global memoization would break LangGraph's purity (checkpointing, replay, visualization). Keeping the cache in `DiscussionState` preserves the framework's guarantees.

## 5. Prompt Caching

### Target
Mark the **role system prompt** and the **static project/feature meta block** with `cache_control: ephemeral`. Discussion context (dynamic) is **not** cached.

### Current (`core/agents.py:44-46`)
```python
messages = [
    SystemMessage(content=system_prompt),
    HumanMessage(content=human_prompt),
]
```

### New
```python
system_blocks = [
    {
        "type": "text",
        "text": role_system_prompt,
        "cache_control": {"type": "ephemeral"},
    },
    {
        "type": "text",
        "text": project_meta_block,  # project_description + feature_name + feature_description
        "cache_control": {"type": "ephemeral"},
    },
]
messages = [
    SystemMessage(content=system_blocks),
    HumanMessage(content=discussion_context_block),
]
```

### Rules
- Cached: role system prompt, project/feature meta (invariant within a round)
- Not cached: discussion context (changes every turn)
- Anthropic requires ≥1024 cached tokens — role + project meta typically meets this. If not, the API silently ignores the marker; behavior is unaffected.
- Apply across all LLM call sites: agents, PM, summarizer, build nodes.

### Expected impact
After the first call, cached prefix billed at ~10% of normal input cost.

## 6. Test Strategy

### Unit tests (new `tests/` directory)

**`tests/test_context_cache.py`**
- Empty state → empty cache, `context_cache_len == 0`
- Adding entries → only new entries appended; previous portion of `context_cache` byte-identical
- Calling builder twice without log changes → same result, `context_cache_len` unchanged
- Round reset → cache cleared

**`tests/test_llm_injection.py`**
- `build_llm()` produces an instance
- After `build_graph(llm)`, all node factories reference the same instance (verified via mock + `id()`)
- `cli.py` does not import `ChatAnthropic` directly (static import check)

**`tests/test_prompt_cache.py`**
- Agent message builder produces `SystemMessage` whose `content` is a list of blocks
- First two blocks contain `cache_control: {"type": "ephemeral"}`
- `HumanMessage` (discussion) has no `cache_control`

### Integration verification

**`test_local.py` extension or `tests/test_integration_phase_b.py`**
- Run a fixed scenario with a fixed seed
- Compare `cost_tracker` token counts vs. baseline → expect ≥30% reduction
- Compare counts of `decisions` and `unresolved` items → within ±20% of baseline (semantic equivalence)
- Baseline numbers stored in a committed JSON fixture for regression detection

**Run command**: `pytest tests/ -v && python test_local.py`

## 7. Implementation Order

Each step ends with passing tests before proceeding.

1. Create `core/llm.py` with `build_llm()` and unit tests
2. Add cache fields to `DiscussionState` in `core/state.py`
3. Refactor `core/agents.py`: incremental `_build_discussion_context` + accept injected LLM
4. Refactor `core/summarizer.py` and `core/code_generator.py` to accept injected LLM
5. Update `core/graph.py`: `build_graph(llm)` signature, forward LLM to node factories
6. Update `cli.py`: build LLM once, inject into graph; reset cache fields per feature
7. Apply prompt caching across agents → PM → summarizer → build nodes
8. Capture baseline (pre-change branch), then run integration verification on the new branch

## 8. Risks & Mitigations

| Risk | Mitigation |
|---|---|
| `cache_control` format depends on `langchain-anthropic` version | Verify version in `requirements.txt` supports list-of-blocks `SystemMessage` content; pin if necessary |
| State cache fields conflict with LangGraph checkpointing | TypedDict additions are backward-compatible; covered by integration test |
| `context_cache_len` desync bug | Unit tests are the first line of defense; reviewed during code review |
| Prefix below 1024 tokens disables caching | Role + project meta usually meets the threshold; behavior is correct either way |
| Token-reduction target (30%) not met | Treat as a tuning signal — investigate via `cost_tracker` per node; do not roll back unless functional regression |

**Rollback**: each step is a separate commit; `git revert` per step if needed.

## 9. Success Criteria

- All new unit tests pass
- Integration test shows ≥30% token reduction vs. baseline
- `decisions`/`unresolved` counts within ±20% of baseline
- No change to CLI UX, persona behavior, or graph topology
- No new global mutable state introduced
