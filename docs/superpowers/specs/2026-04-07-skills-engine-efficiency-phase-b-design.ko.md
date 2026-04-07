# Brawl & Build — 스킬/엔진 효율화 (Phase B) 설계

**작성일**: 2026-04-07
**상태**: 설계 승인 완료, 구현 계획 작성 대기
**범위**: Phase B (빠른 승리). Phase C (병렬화)는 별도 스펙으로 분리.

## 1. 목표 & 범위

토론 흐름, LangGraph 토폴로지, 페르소나 동작, CLI UX를 **변경하지 않고** 토큰 비용과 지연을 30-50% 절감한다.

**포함 범위**
1. LLM 의존성 주입 (팩토리 기반 싱글톤화)
2. State 기반 증분 discussion-context 캐시
3. 정적 prefix(role system + project 메타)에 대한 Anthropic prompt caching

**제외 범위 (Phase C로 분리)**
- BE/FE/Designer 라운드 내 병렬화
- Build 단계 병렬화 (api_spec / shared / be / fe)
- LangGraph 토폴로지 변경

## 2. 배경 — 감사 결과

현재 코드에서 발견된 주요 비효율:

| # | 이슈 | 위치 |
|---|---|---|
| 1 | `ChatAnthropic` 인스턴스가 실행마다 7+개 생성됨 (싱글톤 부재) | `core/agents.py:13,82`, `core/summarizer.py:30`, `core/code_generator.py:127` |
| 2 | `_build_discussion_context()`가 매 호출마다 풀로그 재구성 (O(n²)) | `core/agents.py:16,85,159-173` |
| 5 | Anthropic prompt caching (`cache_control`) 미사용 | `core/agents.py:44-46`, `core/code_generator.py:164-166` |

Phase B는 #1, #2, #5를 다룬다. Phase C에서 #3(직렬 build)과 라운드 내 병렬화를 다룬다.

## 3. 아키텍처 변경

### 신규 모듈
- **`core/llm.py`** — `build_llm(config) -> ChatAnthropic` 팩토리 노출. LLM 생성의 단일 진입점. 모델명, temperature, timeout, 향후 클라이언트 설정을 중앙화.

### 변경 모듈
- **`cli.py`** — 시작 시 `llm = build_llm(...)` 1회 호출, `build_graph(llm)`에 주입.
- **`core/graph.py`** — `build_graph(llm)`이 LLM을 받아 모든 노드 팩토리에 전달.
- **`core/agents.py`** — `create_agent_node(role, llm)`, `create_pm_moderator_node(llm)`이 `ChatAnthropic`을 내부에서 만들지 않고 `llm`을 인자로 받음.
- **`core/summarizer.py`** — `summarize(state, llm)` 형태로 `llm` 파라미터 추가.
- **`core/code_generator.py`** — build 노드 팩토리도 `llm` 주입 받음.
- **`core/state.py`** — `DiscussionState`에 두 필드 추가:
  - `context_cache: str` (기본값 `""`)
  - `context_cache_len: int` (기본값 `0`)

### 불변 (변경 없음)
- LangGraph 토폴로지와 노드 순서
- PM 허브 토론 흐름
- 페르소나 정의와 프롬프트
- CLI UX와 출력
- `models/`의 Pydantic 스키마

## 4. 증분 컨텍스트 캐시

### 현재 동작 (`core/agents.py:159-173`)
```python
def _build_discussion_context(state):
    parts = []
    for entry in state["discussion_log"]:
        parts.append(f"[{entry['role']}] {entry['message']}")
    return "\n".join(parts)
```
호출마다 전체 문자열 재구성 → 라운드 누적 O(n²).

### 변경 후
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

각 에이전트/PM 노드는 반환 dict에 갱신된 `context_cache`와 `context_cache_len`을 포함시킨다. LangGraph가 state를 통해 자연스럽게 전파 — 숨은 전역 상태 없음.

**캐시 리셋**: 새 feature/라운드 시작 시 `cli.py`가 캐시 필드를 명시적으로 비워 이전 라운드 내용이 누수되지 않게 한다.

**복잡도**: O(n²) → O(n).

**state 기반 선택 이유**: 외부 전역 메모이즈는 LangGraph의 순수성(체크포인트, 재실행, 시각화)을 깨뜨린다. 캐시를 `DiscussionState`에 두면 프레임워크 보장이 유지된다.

## 5. Prompt Caching

### 적용 대상
**role system prompt**와 **정적 project/feature 메타 블록**에 `cache_control: ephemeral` 마킹. discussion context(동적)는 캐시하지 **않음**.

### 현재 (`core/agents.py:44-46`)
```python
messages = [
    SystemMessage(content=system_prompt),
    HumanMessage(content=human_prompt),
]
```

### 변경 후
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

### 규칙
- 캐시 대상: role system prompt, project/feature 메타 (라운드 내내 불변)
- 비캐시: discussion context (매 발언마다 변경)
- Anthropic은 캐시 prefix가 1024 토큰 이상일 때만 적용 — role + project 메타는 보통 충족. 미달이면 API가 마커를 무시하며 동작은 영향 없음.
- 모든 LLM 호출 지점에 적용: agents, PM, summarizer, build 노드.

### 기대 효과
첫 호출 이후 캐시된 prefix는 일반 입력 토큰 비용의 ~10%로 청구.

## 6. 테스트 전략

### 단위 테스트 (신규 `tests/` 디렉터리)

**`tests/test_context_cache.py`**
- 빈 state → 빈 캐시, `context_cache_len == 0`
- 항목 추가 → 새 항목만 append, 기존 `context_cache` 부분은 바이트 동일
- 로그 변화 없이 빌더 두 번 호출 → 동일 결과, `context_cache_len` 불변
- 라운드 리셋 → 캐시 비워짐

**`tests/test_llm_injection.py`**
- `build_llm()`이 인스턴스 반환
- `build_graph(llm)` 후 모든 노드 팩토리가 동일 인스턴스 참조 (mock + `id()`로 검증)
- `cli.py`가 `ChatAnthropic`을 직접 import 하지 않음 (정적 import 검사)

**`tests/test_prompt_cache.py`**
- 에이전트 메시지 빌더가 생성한 `SystemMessage`의 `content`가 블록 리스트
- 첫 두 블록에 `cache_control: {"type": "ephemeral"}` 존재
- `HumanMessage`(discussion)에는 `cache_control` 없음

### 통합 검증

**`test_local.py` 확장 또는 `tests/test_integration_phase_b.py`**
- 고정 시드/시나리오로 실행
- `cost_tracker` 토큰 카운트를 baseline과 비교 → 30% 이상 감소 기대
- `decisions`와 `unresolved` 항목 수가 baseline ±20% 이내 (의미적 동등성)
- baseline 수치는 회귀 감지용으로 커밋된 JSON 픽스처에 저장

**실행 명령**: `pytest tests/ -v && python test_local.py`

## 7. 구현 순서

각 단계는 테스트 통과 확인 후 다음으로 진행.

1. `core/llm.py` 생성 + 단위 테스트
2. `core/state.py`에 캐시 필드 추가
3. `core/agents.py` 리팩터: 증분 `_build_discussion_context` + LLM 주입 시그니처
4. `core/summarizer.py`, `core/code_generator.py` LLM 주입 적용
5. `core/graph.py` 업데이트: `build_graph(llm)` 시그니처, 노드 팩토리에 LLM 전달
6. `cli.py` 업데이트: LLM 1회 생성 후 graph에 주입; feature마다 캐시 필드 리셋
7. Prompt caching 적용 (agents → PM → summarizer → build 노드 순)
8. baseline 측정(변경 전 브랜치)→ 신규 브랜치에서 통합 검증 실행

## 8. 리스크 & 완화

| 리스크 | 완화 |
|---|---|
| `cache_control` 포맷이 `langchain-anthropic` 버전에 따라 다름 | `requirements.txt`에서 list-of-blocks `SystemMessage` content 지원 버전 확인, 필요 시 핀 |
| State 캐시 필드가 LangGraph 체크포인트와 충돌 | TypedDict 추가는 하위 호환; 통합 테스트로 확인 |
| `context_cache_len` 동기화 버그 | 단위 테스트가 1차 방어선; 코드 리뷰에서 재확인 |
| Prefix가 1024 토큰 미만으로 캐시 비활성 | role + project 메타는 보통 충족; 미달이어도 동작은 정상 |
| 토큰 절감 목표(30%) 미달 | 튜닝 시그널로 간주 — `cost_tracker`로 노드별 분석. 기능 회귀가 아니면 롤백하지 않음 |

**롤백**: 각 단계가 별도 commit → 필요 시 단계별 `git revert`.

## 9. 성공 기준

- 모든 신규 단위 테스트 통과
- 통합 테스트에서 baseline 대비 토큰 30% 이상 감소
- `decisions`/`unresolved` 항목 수가 baseline ±20% 이내
- CLI UX, 페르소나 동작, 그래프 토폴로지 변경 없음
- 새로운 전역 가변 상태 도입 없음
