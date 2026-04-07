# Skills/Engine Efficiency (Phase B) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Reduce token cost and latency 30-50% in `brawl-and-build` by injecting a single LLM, caching discussion context incrementally in state, and applying Anthropic prompt caching to the static prefix — without changing graph topology, persona behavior, or CLI UX.

**Architecture:** Introduce a `core/llm.py` factory that constructs `ChatAnthropic` once. Thread that instance through `build_discussion_graph(llm)` into all node factories (`agents`, `summarizer`, `code_generator`). Add `context_cache` / `context_cache_len` fields to `DiscussionState` so `_build_discussion_context` becomes O(n) append-only. Wrap the role system prompt and the static project/feature meta block in `cache_control: ephemeral` content blocks at every LLM call site.

**Tech Stack:** Python 3.11+, LangGraph, langchain-anthropic ≥0.3.0, Anthropic prompt caching, pytest.

**Spec:** `docs/superpowers/specs/2026-04-07-skills-engine-efficiency-phase-b-design.md`

---

## File Structure

**Created**
- `core/llm.py` — single `build_llm(model, max_tokens)` factory; the only place that imports `ChatAnthropic`.
- `tests/__init__.py` — empty marker.
- `tests/conftest.py` — shared `FakeLLM` and fixtures.
- `tests/test_context_cache.py` — unit tests for incremental cache.
- `tests/test_llm_injection.py` — verifies single LLM instance reaches every node.
- `tests/test_prompt_cache.py` — verifies `cache_control` markers on system blocks.
- `tests/test_integration_phase_b.py` — runs `run_discussion` end-to-end with `FakeLLM` and asserts call counts + state shape.

**Modified**
- `core/state.py` — add `context_cache: str`, `context_cache_len: int` to `DiscussionState`.
- `core/agents.py` — `create_agent_node(role, llm)`, `create_pm_moderator_node(pm_role, mode, target_role, llm)`. Rewrite `_build_discussion_context` to be append-only and return `(cache, new_len)`. System prompt becomes a list of blocks with `cache_control`.
- `core/summarizer.py` — `create_summarizer_node(llm)` accepts injected llm; system prompt becomes blocked.
- `core/code_generator.py` — `create_build_node(role, llm)` accepts injected llm; system prompt becomes blocked.
- `core/graph.py` — `build_discussion_graph(roles, llm, summarizer_llm, max_rounds, enable_build)`; `run_discussion` builds the LLMs once via `build_llm`.
- `cli.py` — no LLM construction; passes model name into `run_discussion` (which now constructs via `build_llm`).

**Out of scope** (deferred to Phase C): parallel build, intra-round agent parallelism, graph topology changes.

---

## Conventions Used in This Plan

- `discussion_log` entries use the key `content` (not `message`) — see `core/agents.py:55`.
- Anthropic content blocks for `SystemMessage` are passed as a Python list of dicts: `[{"type": "text", "text": "...", "cache_control": {"type": "ephemeral"}}]`. `langchain-anthropic>=0.3.0` forwards this verbatim.
- Tests use a `FakeLLM` that records every `invoke()` call (messages + identity) and returns a canned `AIMessage`. No real network calls in unit/integration tests.
- All commits use Conventional Commits prefixes (`feat:`, `refactor:`, `test:`, `chore:`).

---

## Task 1: Add `tests/` scaffold and `FakeLLM` fixture

**Files:**
- Create: `tests/__init__.py`
- Create: `tests/conftest.py`

- [ ] **Step 1: Create empty package marker**

```python
# tests/__init__.py
```

- [ ] **Step 2: Write the FakeLLM fixture**

```python
# tests/conftest.py
"""Shared fixtures for Phase B tests."""

from dataclasses import dataclass, field
from typing import Any
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
```

- [ ] **Step 3: Verify pytest discovers the package**

Run: `cd /Users/rowdy/Documents/since/brawl-and-build && venv/bin/pytest tests/ --collect-only -q`
Expected: `no tests ran` with no collection errors.

- [ ] **Step 4: Commit**

```bash
git add tests/__init__.py tests/conftest.py
git commit -m "test: add FakeLLM fixture and tests package scaffold"
```

---

## Task 2: Create `core/llm.py` factory

**Files:**
- Create: `core/llm.py`
- Test: `tests/test_llm_injection.py` (extended in Task 7)

- [ ] **Step 1: Write the failing test**

```python
# tests/test_llm_injection.py
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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `venv/bin/pytest tests/test_llm_injection.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'core.llm'`.

- [ ] **Step 3: Create the factory**

```python
# core/llm.py
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
```

- [ ] **Step 4: Run test to verify it passes**

Run: `venv/bin/pytest tests/test_llm_injection.py -v`
Expected: PASS (2 tests).

- [ ] **Step 5: Commit**

```bash
git add core/llm.py tests/test_llm_injection.py
git commit -m "feat(llm): add core.llm.build_llm factory"
```

---

## Task 3: Add cache fields to `DiscussionState`

**Files:**
- Modify: `core/state.py`

- [ ] **Step 1: Add the two new fields**

Edit `core/state.py`. After the `previous_context: str` line and before the `# Build 페이즈` comment, insert:

```python
    # Phase B: incremental discussion-context cache (O(n²) → O(n))
    context_cache: str
    context_cache_len: int
```

- [ ] **Step 2: Verify the file still parses**

Run: `venv/bin/python -c "from core.state import DiscussionState; print(DiscussionState.__annotations__['context_cache'])"`
Expected: `<class 'str'>`

- [ ] **Step 3: Commit**

```bash
git add core/state.py
git commit -m "feat(state): add context_cache fields for incremental builder"
```

---

## Task 4: Rewrite `_build_discussion_context` to be append-only (TDD)

**Files:**
- Test: `tests/test_context_cache.py`
- Modify: `core/agents.py:159-173`

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_context_cache.py
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
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `venv/bin/pytest tests/test_context_cache.py -v`
Expected: FAILures — current `_build_discussion_context` returns a single string, not a tuple.

- [ ] **Step 3: Replace `_build_discussion_context` in `core/agents.py`**

Replace the existing function (lines 159-173) with:

```python
def _build_discussion_context(state: DiscussionState) -> tuple[str, int]:
    """Append-only builder for the discussion-context string.

    Returns (cache, new_len) so the calling node can propagate both back into
    LangGraph state. This makes the builder O(n) over the run instead of O(n²)
    because previously-formatted entries are reused verbatim.

    Round headers are emitted whenever the round number changes between the
    last cached entry and the next new entry.
    """
    log = state.get("discussion_log", [])
    cached_len = state.get("context_cache_len", 0) or 0
    cache = state.get("context_cache", "") or ""

    if len(log) <= cached_len:
        return cache, cached_len

    # Determine the round at the tail of the cached portion so we know whether
    # the next new entry needs a fresh round header.
    last_round = log[cached_len - 1]["round"] if cached_len > 0 else None

    new_lines: list[str] = []
    for entry in log[cached_len:]:
        if entry["round"] != last_round:
            last_round = entry["round"]
            new_lines.append(f"\n### 라운드 {last_round}")
        new_lines.append(f"**[{entry['role']}]**: {entry['content']}")

    appended = "\n".join(new_lines)
    cache = f"{cache}\n{appended}" if cache else appended
    return cache, len(log)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `venv/bin/pytest tests/test_context_cache.py -v`
Expected: PASS (5 tests).

- [ ] **Step 5: Commit**

```bash
git add core/agents.py tests/test_context_cache.py
git commit -m "refactor(agents): make discussion-context builder append-only"
```

Note: agent nodes still call this with the old single-return signature in this commit; Task 5 fixes the call sites. Tests of this isolated function pass independently.

---

## Task 5: Inject LLM and propagate cache through `core/agents.py`

**Files:**
- Modify: `core/agents.py`

- [ ] **Step 1: Update `create_agent_node` signature and body**

Replace the existing `create_agent_node` (lines 10-65) with:

```python
def create_agent_node(role: RoleConfig, llm, model: str = "claude-sonnet-4-20250514"):
    """Create an agent node bound to an injected LLM client.

    The model name is kept only for cost-tracker labeling; no LLM is
    constructed inside this factory.
    """

    def agent_node(state: DiscussionState) -> dict:
        discussion_context, new_cache_len = _build_discussion_context(state)

        prev_ctx = state.get("previous_context", "")
        prev_section = (
            f"\n## 이전 기능 토론에서 결정된 사항\n{prev_ctx}" if prev_ctx else ""
        )

        # Static block: project + feature metadata. Stable across the entire
        # round, so it is a prompt-cache candidate (see Task 8).
        project_meta = f"""## 프로젝트 정보
- 프로젝트: {state["project_description"]}
- 논의 기능: {state["feature_name"]}
{f'- 기능 설명: {state["feature_description"]}' if state.get("feature_description") else ""}
{prev_section}"""

        # Dynamic block: current round + discussion log. Changes every turn.
        dynamic_block = f"""## 현재 토론 상황
- 라운드: {state["current_round"]}/{state["max_rounds"]}
- 당신의 역할: {role.name} ({role.title})
- 주요 관심 영역: {", ".join(role.focus_areas)}

## 이전 토론 내용
{discussion_context if discussion_context else "(첫 발언입니다. 기능에 대한 초기 의견을 제시하세요.)"}

## 요청
위 맥락을 바탕으로 {role.name} ({role.title}) 관점에서 의견을 제시하세요.
- 이전 기능에서 결정된 사항과 일관성을 유지하세요
- 이전 발언자들의 의견에 대해 동의/반대/보완 의견을 밝히세요
- 당신의 전문 영역에서 놓치고 있는 부분을 지적하세요
- 구체적인 제안이나 대안을 포함하세요
- 300자 이내로 핵심만 간결하게 답변하세요"""

        system_blocks = _cached_system_blocks(role.system_prompt, project_meta)

        response = llm.invoke([
            SystemMessage(content=system_blocks),
            HumanMessage(content=dynamic_block),
        ])

        get_tracker().track(response, model=model)

        new_entry = {
            "role": role.name,
            "round": state["current_round"],
            "content": response.content,
        }
        updated_log = state.get("discussion_log", []) + [new_entry]

        return {
            "discussion_log": updated_log,
            "messages": [response],
            "context_cache": discussion_context,
            "context_cache_len": new_cache_len,
        }

    return agent_node
```

- [ ] **Step 2: Update `create_pm_moderator_node` signature and body**

Replace the existing `create_pm_moderator_node` (lines 68-156) with:

```python
def create_pm_moderator_node(
    pm_role: RoleConfig,
    llm,
    mode: str = "question",
    target_role: str = "",
    model: str = "claude-sonnet-4-20250514",
):
    """PM moderator node bound to an injected LLM client.

    mode:
      - "kickoff": round opener
      - "respond": follow-up to a member
      - "wrap_up": round summary
    """

    def pm_moderator_node(state: DiscussionState) -> dict:
        discussion_context, new_cache_len = _build_discussion_context(state)

        if mode == "kickoff":
            instruction = f"""당신은 이번 라운드의 사회자입니다.
라운드 {state["current_round"]}을 시작합니다.

이전 토론 내용을 검토하고:
- 이번 라운드에서 논의할 핵심 쟁점 2-3개를 제시하세요
- 각 팀원(BE, FE, Designer)에게 구체적인 질문을 던지세요
- 이전 라운드의 미해결 사항이 있다면 언급하세요
- 300자 이내로 간결하게 정리하세요"""
        elif mode == "respond":
            instruction = f"""방금 {target_role}의 의견을 들었습니다.
PM 사회자로서:
- {target_role}의 의견에서 핵심 포인트를 짚어주세요
- 동의/반대/보완할 부분을 명확히 하세요
- 다른 팀원의 관점에서 고려할 점을 제기하세요
- 필요하면 추가 질문을 던지세요
- 200자 이내로 간결하게 정리하세요"""
        elif mode == "wrap_up":
            instruction = f"""라운드 {state["current_round"]}의 모든 의견을 들었습니다.
PM 사회자로서 이번 라운드를 종합 정리하세요:
- 합의된 사항을 명시하세요
- 의견이 갈린 쟁점을 정리하세요
- 다음 라운드에서 다뤄야 할 사항을 제시하세요
- 300자 이내로 간결하게 정리하세요"""
        else:
            instruction = "PM으로서 의견을 제시하세요."

        project_meta = f"""## 프로젝트 정보
- 프로젝트: {state["project_description"]}
- 논의 기능: {state["feature_name"]}
{f'- 기능 설명: {state["feature_description"]}' if state.get("feature_description") else ""}"""

        dynamic_block = f"""## 현재 토론 상황
- 라운드: {state["current_round"]}/{state["max_rounds"]}
- 당신의 역할: PM 사회자 ({pm_role.title})

## 이전 토론 내용
{discussion_context if discussion_context else "(첫 라운드입니다.)"}

## 요청
{instruction}"""

        system_blocks = _cached_system_blocks(pm_role.system_prompt, project_meta)

        response = llm.invoke([
            SystemMessage(content=system_blocks),
            HumanMessage(content=dynamic_block),
        ])

        get_tracker().track(response, model=model)

        tag = f"PM({mode})"
        if mode == "respond":
            tag = f"PM→{target_role}"

        new_entry = {
            "role": tag,
            "round": state["current_round"],
            "content": response.content,
        }
        updated_log = state.get("discussion_log", []) + [new_entry]

        return {
            "discussion_log": updated_log,
            "messages": [response],
            "context_cache": discussion_context,
            "context_cache_len": new_cache_len,
        }

    return pm_moderator_node
```

- [ ] **Step 3: Add the cached-system-blocks helper at the bottom of `core/agents.py`**

Append after `_build_discussion_context`:

```python
def _cached_system_blocks(role_system_prompt: str, project_meta: str) -> list[dict]:
    """Build a SystemMessage content list with prompt-cache markers.

    Anthropic charges cached input tokens at ~10% after the first call. We
    mark the role system prompt and the static project meta block as
    ephemeral cache breakpoints. Discussion context is intentionally NOT
    cached because it changes every turn.

    If the combined prefix is below Anthropic's 1024-token threshold the
    marker is silently ignored — behavior is unaffected.
    """
    return [
        {
            "type": "text",
            "text": role_system_prompt,
            "cache_control": {"type": "ephemeral"},
        },
        {
            "type": "text",
            "text": project_meta,
            "cache_control": {"type": "ephemeral"},
        },
    ]
```

- [ ] **Step 4: Verify the module imports cleanly**

Run: `venv/bin/python -c "from core.agents import create_agent_node, create_pm_moderator_node, _cached_system_blocks; print('ok')"`
Expected: `ok`

- [ ] **Step 5: Re-run the cache unit tests**

Run: `venv/bin/pytest tests/test_context_cache.py -v`
Expected: PASS (5 tests still green).

- [ ] **Step 6: Commit**

```bash
git add core/agents.py
git commit -m "refactor(agents): inject LLM, propagate context cache, mark cached blocks"
```

---

## Task 6: Inject LLM into summarizer and code_generator

**Files:**
- Modify: `core/summarizer.py`
- Modify: `core/code_generator.py`

- [ ] **Step 1: Update `create_summarizer_node` signature**

In `core/summarizer.py`, remove the `from langchain_anthropic import ChatAnthropic` import. Replace `create_summarizer_node` (lines 27-61) with:

```python
def create_summarizer_node(llm, model: str = "claude-haiku-4-5-20251001"):
    """Summarizer node bound to an injected LLM client."""

    def summarizer_node(state: DiscussionState) -> dict:
        discussion_text = _format_discussion_log(state)

        project_meta = f"""## 프로젝트: {state["project_description"]}
## 논의 기능: {state["feature_name"]}"""

        dynamic_block = f"""{project_meta}

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
            HumanMessage(content=dynamic_block),
        ])

        get_tracker().track(response, model=model)

        result = _parse_summary_response(response.content)

        return {
            "decisions": result.get("decisions", []),
            "unresolved": result.get("unresolved", []),
            "summary": result.get("summary", "요약 생성 실패"),
            "messages": [response],
        }

    return summarizer_node
```

- [ ] **Step 2: Update `create_build_node` signature in `core/code_generator.py`**

Remove the `from langchain_anthropic import ChatAnthropic` import. Replace `create_build_node` (the function starting around line 118) — change the signature line and remove the internal `llm = ChatAnthropic(...)`:

```python
def create_build_node(role: str, llm, model: str = "claude-sonnet-4-20250514"):
    """Code generation node bound to an injected LLM client.

    role: "be", "fe", "shared", "api_spec"
    """

    system_prompts = {
        "be": BE_CODE_PROMPT,
        "fe": FE_CODE_PROMPT,
        "shared": SHARED_TYPE_PROMPT,
        "api_spec": API_SPEC_PROMPT,
    }
```

Then inside `build_node`, replace the `response = llm.invoke([...])` block with:

```python
        system_blocks = [
            {
                "type": "text",
                "text": system_prompts[role],
                "cache_control": {"type": "ephemeral"},
            },
        ]

        response = llm.invoke([
            SystemMessage(content=system_blocks),
            HumanMessage(content=prompt),
        ])
```

Leave the rest of `build_node` (decisions/summary prompt construction, output appending) untouched.

- [ ] **Step 3: Verify both modules import cleanly**

Run: `venv/bin/python -c "from core.summarizer import create_summarizer_node; from core.code_generator import create_build_node; print('ok')"`
Expected: `ok`

- [ ] **Step 4: Commit**

```bash
git add core/summarizer.py core/code_generator.py
git commit -m "refactor(nodes): inject LLM into summarizer and code_generator"
```

---

## Task 7: Wire injection through `core/graph.py` and `cli.py`

**Files:**
- Modify: `core/graph.py`
- Modify: `cli.py` (if it constructs LLMs anywhere — currently it does not)

- [ ] **Step 1: Update `build_discussion_graph` and `run_discussion`**

Replace the entire `core/graph.py` body below the imports with:

```python
"""LangGraph 토론 그래프 구성 - PM 허브형 + Build 페이즈."""

from langgraph.graph import StateGraph, END
from models.schemas import RoleConfig
from core.state import DiscussionState
from core.agents import create_agent_node, create_pm_moderator_node
from core.summarizer import create_summarizer_node
from core.code_generator import create_build_node
from core.llm import build_llm


def build_discussion_graph(
    roles: list[RoleConfig],
    llm,
    summarizer_llm,
    max_rounds: int = 2,
    model: str = "claude-sonnet-4-20250514",
    summarizer_model: str = "claude-haiku-4-5-20251001",
    enable_build: bool = False,
):
    """Build the PM-hub discussion graph + optional build phase.

    `llm` is reused by every agent/PM/build node. `summarizer_llm` is a
    separate (typically smaller/cheaper) instance because the summarizer uses
    a different default model.
    """

    graph = StateGraph(DiscussionState)

    pm_role = roles[0]
    member_roles = [r for r in roles if r.name != pm_role.name]

    graph.add_node(
        "pm_kickoff",
        create_pm_moderator_node(pm_role, llm, mode="kickoff", model=model),
    )

    for member in member_roles:
        graph.add_node(
            f"agent_{member.name}",
            create_agent_node(member, llm, model=model),
        )
        graph.add_node(
            f"pm_respond_{member.name}",
            create_pm_moderator_node(
                pm_role, llm, mode="respond", target_role=member.name, model=model
            ),
        )

    graph.add_node(
        "pm_wrap_up",
        create_pm_moderator_node(pm_role, llm, mode="wrap_up", model=model),
    )

    def increment_round(state: DiscussionState) -> dict:
        return {"current_round": state["current_round"] + 1}

    graph.add_node("increment_round", increment_round)
    graph.add_node("summarizer", create_summarizer_node(summarizer_llm, model=summarizer_model))

    graph.set_entry_point("pm_kickoff")
    graph.add_edge("pm_kickoff", f"agent_{member_roles[0].name}")

    for i, member in enumerate(member_roles):
        graph.add_edge(f"agent_{member.name}", f"pm_respond_{member.name}")
        if i < len(member_roles) - 1:
            next_member = member_roles[i + 1]
            graph.add_edge(f"pm_respond_{member.name}", f"agent_{next_member.name}")
        else:
            graph.add_edge(f"pm_respond_{member.name}", "pm_wrap_up")

    graph.add_edge("pm_wrap_up", "increment_round")

    def should_continue(state: DiscussionState) -> str:
        if state["current_round"] > state["max_rounds"]:
            return "summarizer"
        return "pm_kickoff"

    graph.add_conditional_edges("increment_round", should_continue)

    if enable_build:
        graph.add_node("build_api_spec", create_build_node("api_spec", llm, model=model))
        graph.add_node("build_shared", create_build_node("shared", llm, model=model))
        graph.add_node("build_be", create_build_node("be", llm, model=model))
        graph.add_node("build_fe", create_build_node("fe", llm, model=model))

        graph.add_edge("summarizer", "build_api_spec")
        graph.add_edge("build_api_spec", "build_shared")
        graph.add_edge("build_shared", "build_be")
        graph.add_edge("build_be", "build_fe")
        graph.add_edge("build_fe", END)
    else:
        graph.add_edge("summarizer", END)

    return graph.compile()


def run_discussion(
    project_description: str,
    feature_name: str,
    feature_description: str = "",
    roles: list[RoleConfig] | None = None,
    max_rounds: int = 2,
    model: str = "claude-sonnet-4-20250514",
    summarizer_model: str = "claude-haiku-4-5-20251001",
    enable_build: bool = False,
    previous_context: str = "",
    llm=None,
    summarizer_llm=None,
) -> DiscussionState:
    """Run a discussion. Builds one LLM per role group and reuses across nodes.

    Tests can pass in `llm` / `summarizer_llm` to inject FakeLLMs.
    """
    from config.roles import DEFAULT_ROLES

    if roles is None:
        roles = DEFAULT_ROLES

    if llm is None:
        llm = build_llm(model=model, max_tokens=2048)
    if summarizer_llm is None:
        summarizer_llm = build_llm(model=summarizer_model, max_tokens=2048)

    app = build_discussion_graph(
        roles,
        llm=llm,
        summarizer_llm=summarizer_llm,
        max_rounds=max_rounds,
        model=model,
        summarizer_model=summarizer_model,
        enable_build=enable_build,
    )

    initial_state: DiscussionState = {
        "project_description": project_description,
        "feature_name": feature_name,
        "feature_description": feature_description,
        "current_round": 1,
        "max_rounds": max_rounds,
        "current_role_index": 0,
        "role_names": [r.name for r in roles],
        "discussion_log": [],
        "messages": [],
        "decisions": [],
        "unresolved": [],
        "summary": "",
        "previous_context": previous_context,
        "build_enabled": enable_build,
        "build_outputs": [],
        # Phase B: per-run cache, reset every run
        "context_cache": "",
        "context_cache_len": 0,
    }

    final_state = app.invoke(initial_state)
    return final_state
```

- [ ] **Step 2: Verify cli.py still works (smoke import)**

Run: `venv/bin/python -c "from cli import main; print('ok')"`
Expected: `ok`. (cli.py never constructed `ChatAnthropic` directly so no edits required there.)

- [ ] **Step 3: Verify `ChatAnthropic` is now imported in exactly one place**

Run: `grep -rn "ChatAnthropic" core/ cli.py`
Expected: only `core/llm.py` shows an import line. `core/agents.py`, `core/summarizer.py`, `core/code_generator.py` must not appear.

If any other file still imports `ChatAnthropic`, remove that import (it should already be unused after Tasks 5-6).

- [ ] **Step 4: Commit**

```bash
git add core/graph.py
git commit -m "refactor(graph): build single LLM per run and inject into all nodes"
```

---

## Task 8: Extend `tests/test_llm_injection.py` to assert single-instance reuse

**Files:**
- Modify: `tests/test_llm_injection.py`

- [ ] **Step 1: Add the injection-reuse test**

Append to `tests/test_llm_injection.py`:

```python
import ast
from pathlib import Path

from core.graph import run_discussion
from tests.conftest import FakeLLM


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
```

- [ ] **Step 2: Run the tests**

Run: `venv/bin/pytest tests/test_llm_injection.py -v`
Expected: PASS (4 tests total).

- [ ] **Step 3: Commit**

```bash
git add tests/test_llm_injection.py
git commit -m "test(llm): assert single-instance reuse and import boundary"
```

---

## Task 9: Verify prompt-cache markers via unit test

**Files:**
- Create: `tests/test_prompt_cache.py`

- [ ] **Step 1: Write the test**

```python
# tests/test_prompt_cache.py
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
```

- [ ] **Step 2: Run the test**

Run: `venv/bin/pytest tests/test_prompt_cache.py -v`
Expected: PASS (3 tests).

- [ ] **Step 3: Commit**

```bash
git add tests/test_prompt_cache.py
git commit -m "test(prompt-cache): verify cache_control markers on system blocks"
```

---

## Task 10: Integration test — full run with FakeLLM

**Files:**
- Create: `tests/test_integration_phase_b.py`

- [ ] **Step 1: Write the integration test**

```python
# tests/test_integration_phase_b.py
"""End-to-end run of the discussion graph using FakeLLM.

Asserts:
  - The graph completes without raising
  - context_cache is populated and grows monotonically
  - Final state contains decisions/unresolved/summary
"""

from core.graph import run_discussion
from tests.conftest import FakeLLM


def test_full_run_with_fake_llm():
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
    assert len(fake.calls) == 16
    assert len(summarizer_fake.calls) == 1

    assert final["decisions"] == ["use postgres"]
    assert final["unresolved"] == ["auth"]
    assert final["summary"] == "ok"

    # Cache must have absorbed every discussion entry
    assert final["context_cache_len"] == len(final["discussion_log"])
    assert final["context_cache"]  # non-empty
    assert "라운드 1" in final["context_cache"]
    assert "라운드 2" in final["context_cache"]


def test_cache_reset_between_runs():
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
    assert final2["context_cache_len"] == len(final2["discussion_log"])
    assert "f2" not in final1["context_cache"]
```

- [ ] **Step 2: Run the integration tests**

Run: `venv/bin/pytest tests/test_integration_phase_b.py -v`
Expected: PASS (2 tests).

- [ ] **Step 3: Run the entire test suite**

Run: `venv/bin/pytest tests/ -v`
Expected: PASS — all tests from Tasks 1-10 green.

- [ ] **Step 4: Commit**

```bash
git add tests/test_integration_phase_b.py
git commit -m "test(integration): end-to-end Phase B verification with FakeLLM"
```

---

## Task 11: Final verification + token-savings smoke check

**Files:**
- (no new files)

- [ ] **Step 1: Confirm import boundary one more time**

Run: `grep -rn "ChatAnthropic" core/ cli.py tests/`
Expected: only `core/llm.py:from langchain_anthropic import ChatAnthropic` and `tests/test_llm_injection.py:from langchain_anthropic import ChatAnthropic` (the test imports it for an isinstance check). No other matches.

- [ ] **Step 2: Run the full test suite once more**

Run: `venv/bin/pytest tests/ -v`
Expected: every test passes.

- [ ] **Step 3: Manual sanity run (requires `ANTHROPIC_API_KEY`)**

Run: `venv/bin/python test_local.py`
Expected: discussion completes; check `output/` for generated artifacts; observe `cost_tracker` totals printed in logs.

If `ANTHROPIC_API_KEY` is not set, skip this step and note "manual run skipped — no API key" in the PR description.

- [ ] **Step 4: Final commit if any cleanup needed**

```bash
git status
# If clean, no commit needed.
```

---

## Self-Review

**Spec coverage:**
- §3 LLM DI factory → Tasks 2, 5, 6, 7
- §3 State cache fields → Task 3
- §4 Incremental context cache → Tasks 4, 5
- §5 Prompt caching markers → Tasks 5, 6, 9
- §6 Unit + integration tests → Tasks 1, 4, 8, 9, 10
- §7 Implementation order → Tasks 2 → 3 → 4 → 5 → 6 → 7 → 8/9/10 (matches spec order)
- §8 Risks (langchain version, cache fields, sync bug, sub-1024 prefix) → addressed by version-pin check, append-only design, and unit tests
- §9 Success criteria → Task 11 verifies import boundary, test suite, and offers manual cost check

**Placeholder scan:** No TBDs, no "implement later", no "similar to Task N" — every code block is complete.

**Type consistency:** `_build_discussion_context` returns `(str, int)` everywhere it is called (Tasks 4, 5). LLM injection signature `create_*(role/pm_role, llm, …)` is consistent across `agents.py`, `summarizer.py`, `code_generator.py`, and `graph.py`. State keys `context_cache` / `context_cache_len` are spelled identically in `state.py`, `agents.py`, `graph.py`, and tests.

---

## Execution Handoff

Plan complete and saved to `docs/superpowers/plans/2026-04-07-skills-engine-efficiency-phase-b.md`. Two execution options:

**1. Subagent-Driven (recommended)** — I dispatch a fresh subagent per task, review between tasks, fast iteration

**2. Inline Execution** — Execute tasks in this session using executing-plans, batch execution with checkpoints

Which approach?
