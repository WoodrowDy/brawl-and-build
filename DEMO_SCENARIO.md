# 🥊 Brawl & Build — 시연 시나리오

## 개요

Claude Desktop에서 MCP를 통해 **멀티에이전트 토론 → 코드 생성 → PR 생성**까지
하나의 대화로 진행하는 시나리오입니다.

**프로젝트**: 소셜 커머스 플랫폼 (Social Commerce Platform)
**스택**: NestJS + React TS + Lerna 모노레포

---

## 시스템 아키텍처

### 전체 흐름

```
┌──────────────────────────────────────────────────────────────────────┐
│  Claude Desktop (사용자 인터페이스)                                      │
│                                                                      │
│  "회원가입 기능을 토론해줘" ──┐                                        │
│                               │  MCP Protocol                        │
│                               ▼                                      │
│  ┌─────────────────────────────────────────────────────────────────┐ │
│  │  mcp_server.py  (FastMCP)                                      │ │
│  │                                                                 │ │
│  │  ┌─────────────┐  ┌──────────┐  ┌───────────┐  ┌───────────┐  │ │
│  │  │init_project │  │ discuss  │  │build_code │  │ create_pr │  │ │
│  │  │   (sync)    │  │ (async)  │  │  (async)  │  │  (sync)   │  │ │
│  │  └──────┬──────┘  └────┬─────┘  └─────┬─────┘  └─────┬─────┘  │ │
│  │         │              │               │              │         │ │
│  │  ┌──────┴──────┐  ┌───┴────┐  ┌───────┴───────┐  ┌───┴──────┐ │ │
│  │  │get_project  │  │get_task│  │  Background   │  │ GitHub   │ │ │
│  │  │  _status    │  │_status │  │   Thread      │  │ REST API │ │ │
│  │  │   (sync)    │  │ (sync) │  │  (polling)    │  │          │ │ │
│  │  └─────────────┘  └────────┘  └───────────────┘  └──────────┘ │ │
│  └─────────────────────────────────────────────────────────────────┘ │
└──────────────────────────────────────────────────────────────────────┘
```

### MCP 도구 관계도

```
사용자 대화
    │
    ├── "프로젝트 초기화해줘"
    │       └── init_project ──→ scaffold_project()
    │                               ├── npx @nestjs/cli new backend
    │                               ├── npx create-vite frontend
    │                               └── mkdir shared
    │
    ├── "기능 토론해줘"
    │       └── discuss ──→ task_id 반환 (즉시)
    │               │
    │               └── Background Thread
    │                       └── run_discussion()  ← LangGraph
    │                               │
    │       get_task_status ◄───────┘ (polling)
    │
    ├── "코드 생성해줘"
    │       └── build_code ──→ task_id 반환 (즉시)
    │               │
    │               └── Background Thread
    │                       ├── run_discussion(enable_build=True)
    │                       └── save_generated_code()
    │
    ├── "PR 만들어줘"
    │       └── create_pr
    │               ├── git branch + add + commit
    │               ├── git push (token auth)
    │               └── GitHub REST API → PR 생성
    │
    └── "프로젝트 상태 보여줘"
            └── get_project_status ──→ .brawl.json 조회
```

### LangGraph 토론 그래프 (내부)

```
Phase 1: Brawl (토론)
═══════════════════════════════════════════════════

 ┌──────────┐     ┌──────┐     ┌─────────────┐
 │PM Kickoff│────▶│  BE  │────▶│PM Respond(BE)│
 └──────────┘     └──────┘     └──────┬──────┘
                                      │
                                      ▼
                               ┌──────┐     ┌──────────────┐
                               │  FE  │────▶│PM Respond(FE) │
                               └──────┘     └──────┬───────┘
                                                   │
                                                   ▼
                              ┌────────┐    ┌────────────────────┐
                              │Designer│───▶│PM Respond(Designer)│
                              └────────┘    └────────┬───────────┘
                                                     │
                                                     ▼
                                              ┌────────────┐
                                              │ PM Wrap-up │
                                              └──────┬─────┘
                                                     │
                                              ┌──────▼──────┐
                                              │Round < Max? │
                                              └──────┬──────┘
                                             Yes │        │ No
                                     ┌───────────┘        ▼
                                     │              ┌───────────┐
                                     │              │ Summarizer│
                                     ▼              └─────┬─────┘
                              ┌──────────┐                │
                              │PM Kickoff│          ──────┘
                              │ (다음 R) │
                              └──────────┘


Phase 2: Build (코드 생성) — enable_build=True 시
═══════════════════════════════════════════════════

 Summarizer
     │
     ▼
 ┌──────────┐   ┌────────────┐   ┌─────────┐   ┌─────────┐
 │ API Spec │──▶│Shared Types│──▶│ BE Code │──▶│ FE Code │──▶ END
 └──────────┘   └────────────┘   └─────────┘   └─────────┘
  OpenAPI yaml   공유 타입 정의    NestJS 모듈    React 컴포넌트
```

### 프로젝트 파일 구조

```
brawl-and-build/                  # 엔진 레포
├── mcp_server.py                 # MCP 진입점 (6 tools)
├── cli.py                        # CLI 진입점
├── main.py                       # FastAPI 진입점
├── .env                          # ANTHROPIC_API_KEY, GITHUB_TOKEN
│
├── core/                         # 핵심 로직
│   ├── graph.py                  # LangGraph 토론 그래프 구성
│   ├── agents.py                 # 역할별 에이전트 노드 (LLM 호출)
│   ├── state.py                  # DiscussionState (TypedDict)
│   ├── summarizer.py             # 토론 요약 노드
│   ├── code_generator.py         # Build 노드 + scaffold + 코드 저장
│   ├── exporter.py               # Markdown/JSON 토론 결과 내보내기
│   ├── project_config.py         # .brawl.json 관리
│   └── cost_tracker.py           # API 비용 추적
│
├── config/
│   └── roles.py                  # PM, BE, FE, Designer 기본 역할 정의
│
└── models/
    └── schemas.py                # Pydantic 모델 (RoleConfig 등)
```

```
target-repo/                      # 대상 프로젝트 (생성됨)
├── .brawl.json                   # 프로젝트 설정 + 완료된 기능 목록
├── lerna.json
├── package.json
│
├── docs/discussions/             # 토론 기록
│   ├── discussion_회원가입_xxx.md
│   └── discussion_회원가입_xxx.json
│
├── api-spec/                     # OpenAPI 명세
│   └── auth-signup.openapi.yaml
│
└── packages/
    ├── backend/                  # NestJS (CLI scaffold)
    │   ├── src/
    │   │   ├── app.module.ts
    │   │   └── auth/             # ← 생성된 기능 모듈
    │   └── package.json
    │
    ├── frontend/                 # React + Vite (CLI scaffold)
    │   ├── src/
    │   │   ├── App.tsx
    │   │   ├── components/       # ← 생성된 컴포넌트
    │   │   └── hooks/            # ← 생성된 훅
    │   └── package.json
    │
    └── shared/                   # 공유 타입
        └── src/types/            # ← 생성된 타입 정의
```

### 비동기 처리 흐름

```
Claude Desktop                 MCP Server                  Background
    │                              │                           │
    │── discuss("회원가입") ──────▶│                           │
    │                              │── Thread.start() ────────▶│
    │◀── {task_id: "abc123"} ─────│                           │
    │                              │                           │── run_discussion()
    │── get_task_status("abc") ──▶│                           │   (LLM 호출 x N)
    │◀── {status: "running"} ─────│                           │
    │                              │                           │
    │   ... (5~10초 간격 폴링) ... │                           │
    │                              │                           │
    │── get_task_status("abc") ──▶│                           │
    │◀── {status: "running"} ─────│                           │
    │                              │                           │
    │── get_task_status("abc") ──▶│◀── _finish_task() ────────│
    │◀── {status: "completed",    │                           │
    │     result: {...}} ──────────│                           │
    │                              │                           │
```

---

## 사전 준비

```bash
# 1. 빈 GitHub 레포 생성 (e.g. social-commerce)
gh repo create social-commerce --public --clone
cd social-commerce
git commit --allow-empty -m "init"
git push origin main

# 2. brawl-and-build venv 의존성 확인
cd ~/Documents/since/brawl-and-build
source venv/bin/activate
pip install -r requirements.txt

# 3. .env 확인
cat .env
# ANTHROPIC_API_KEY=sk-ant-...
# GITHUB_TOKEN=ghp_...

# 4. Claude Desktop config 확인
# brawl-and-build MCP가 등록되어 있어야 함
# env에 ANTHROPIC_API_KEY, GITHUB_TOKEN 설정

# 5. Claude Desktop 재시작
```

---

## 시연 플로우

### Step 1. 프로젝트 초기화

**Claude Desktop에 입력:**
> "소셜 커머스 플랫폼 프로젝트를 `/Users/rowdy/Documents/since/social-commerce` 경로에 초기화해줘"

**기대 동작:**
- `init_project` 호출
- `.brawl.json` 생성
- `npx @nestjs/cli new backend` → NestJS scaffold
- `npx create-vite frontend --template react-ts` → React scaffold
- `packages/shared` 수동 생성

**기대 응답:**
```
프로젝트 '소셜 커머스 플랫폼' 초기화 완료!
- packages/backend (NestJS)
- packages/frontend (React + TypeScript + Vite)
- packages/shared (공유 타입)
```

---

### Step 2. 기능 토론 (Brawl)

**Claude Desktop에 입력:**
> "사용자 회원가입 기능을 토론해줘. 이메일/비밀번호 기반이고, 소셜 로그인(Google, Kakao)도 지원해야 해"

**기대 동작:**
- `discuss` 호출 → task_id 즉시 반환
- Claude가 자동으로 `get_task_status` 폴링
- PM, BE, FE, Designer 에이전트가 2라운드 토론
- 토론 결과 markdown/json 저장

**기대 응답 (폴링 후):**
```
토론이 완료되었습니다!

📋 결정 사항:
- JWT + Refresh Token 기반 인증
- Passport.js로 소셜 로그인 (Google, Kakao) 처리
- 프론트엔드: React Hook Form + Zod validation
- 회원가입 완료 후 이메일 인증 플로우 추가

⚠️ 미해결:
- 이메일 인증 만료 시간 (24h vs 48h)
- 소셜 로그인 시 추가 정보 입력 화면 필요 여부
```

---

### Step 3. 코드 생성 (Build)

**Claude Desktop에 입력:**
> "회원가입 기능 코드를 생성해줘"

**기대 동작:**
- `build_code` 호출 → task_id 즉시 반환
- 토론 결과를 기반으로 코드 생성 (이전 토론 자동 참조)
- NestJS: auth 모듈, controller, service, dto, entity
- React: SignupForm 컴포넌트, useAuth 훅, API 클라이언트
- Shared: 타입 정의
- API Spec: OpenAPI yaml

**기대 응답 (폴링 후):**
```
코드 생성 완료!

📁 생성된 파일:
Backend:
  - src/auth/auth.module.ts
  - src/auth/auth.controller.ts
  - src/auth/auth.service.ts
  - src/auth/dto/signup.dto.ts
  - src/auth/entities/user.entity.ts

Frontend:
  - src/components/Signup/SignupForm.tsx
  - src/hooks/useAuth.ts
  - src/api/auth.api.ts

Shared:
  - src/types/auth.types.ts
  - src/types/user.types.ts

API Spec:
  - api-spec/auth-signup.openapi.yaml
```

---

### Step 4. PR 생성

**Claude Desktop에 입력:**
> "회원가입 기능 PR 만들어줘"

**기대 동작:**
- `create_pr` 호출
- `feature/xxxxxxxx` 브랜치 생성 (md5 해시)
- 모든 생성 코드 커밋
- GitHub 토큰으로 push
- GitHub REST API로 PR 생성
- 토론 결과가 PR description에 자동 포함

**기대 응답:**
```
PR이 생성되었습니다! 🎉
https://github.com/WoodrowDy/social-commerce/pull/1

브랜치: feature/a1b2c3d4
결정 사항과 API 명세가 PR description에 포함되어 있습니다.
```

---

### Step 5. 이어서 다음 기능 (Feature Chaining)

**Claude Desktop에 입력:**
> "상품 등록 기능을 토론해줘. 판매자가 상품명, 가격, 이미지, 카테고리를 입력해서 등록하는 기능이야"

**기대 동작:**
- 이전 "사용자 회원가입" 토론 결과가 자동으로 컨텍스트에 주입
- 에이전트들이 이전 결정사항을 참조하여 토론
  (예: "회원가입에서 결정한 JWT 인증을 상품 등록 API에도 적용")

> "코드 생성하고 PR까지 만들어줘"

**기대 동작:**
- build_code → create_pr 순차 실행
- 새 브랜치 + 새 PR 자동 생성

---

## 핵심 포인트 (시연 시 강조)

1. **자연어로 기능 정의** — 기획서 없이 대화만으로 기능 구현
2. **멀티에이전트 토론** — PM/BE/FE/Designer가 각자 관점에서 논의
3. **결정 기반 코드 생성** — 토론에서 합의된 내용이 코드에 반영
4. **Feature Chaining** — 이전 토론이 다음 토론의 컨텍스트로 자동 연결
5. **원클릭 PR** — 코드 생성부터 GitHub PR까지 자동화
6. **비동기 처리** — 긴 작업도 타임아웃 없이 안정적 실행

---

## 트러블슈팅

### 환경 문제

| 증상 | 원인 | 해결 |
|------|------|------|
| `GITHUB_TOKEN이 설정되지 않았습니다` | .env 또는 MCP env 누락 | `.env`에 토큰 추가 후 Claude Desktop 재시작 |
| `ANTHROPIC_API_KEY` 에러 | 키 만료 또는 누락 | https://console.anthropic.com 에서 재발급 |
| `ModuleNotFoundError: 'mcp'` | venv에 mcp 미설치 | `pip install "mcp[cli]>=1.0.0"` |
| `ModuleNotFoundError: 'requests'` | venv에 requests 미설치 | `pip install requests` |
| MCP 도구가 Claude Desktop에 안 보임 | 설정 오류 또는 서버 크래시 | config 경로 확인 + Claude Desktop 재시작 |

### 실행 문제

| 증상 | 원인 | 해결 |
|------|------|------|
| `discuss` 호출 후 응답 없음 | LLM API 키 문제 | `.env` ANTHROPIC_API_KEY 확인 |
| scaffold timeout (120s 초과) | npm registry 느림 | 재시도 또는 `--init` 따로 실행 |
| `get_task_status` not_found | 서버 재시작으로 in-memory task 유실 | discuss/build_code 다시 실행 |
| build_code에서 코드가 잘림 | LLM 토큰 제한 (max_tokens) | 복잡한 기능은 작게 분할하여 토론 |
| `branch already exists` | 같은 feature로 재실행 | 자동 처리됨 (기존 브랜치 삭제 후 재생성) |

### GitHub / PR 문제

| 증상 | 원인 | 해결 |
|------|------|------|
| `git push` 인증 실패 | GITHUB_TOKEN 권한 부족 | `repo` 전체 권한 필요 (Settings → Tokens) |
| `HTTP 404` PR 생성 실패 | owner/repo 추출 실패 | `git remote -v`로 origin URL 확인 |
| `HTTP 422` PR 생성 실패 | 베이스 브랜치 없음 또는 동일 커밋 | main 브랜치 존재 여부, 변경 파일 유무 확인 |
| `PR already exists` | 같은 head→base PR 존재 | 정상 — skip 처리됨 |

---

## MCP 도구 목록

| 도구 | 타입 | 설명 |
|------|------|------|
| `init_project` | sync | 프로젝트 초기화 + CLI scaffold |
| `discuss` | async | 멀티에이전트 토론 (Brawl) |
| `build_code` | async | 토론 + 코드 생성 (Build) |
| `get_task_status` | sync | 비동기 작업 상태 폴링 |
| `create_pr` | sync | 브랜치 생성 + 커밋 + PR (GitHub API) |
| `get_project_status` | sync | .brawl.json 및 토론 기록 조회 |

---

## 로컬 테스트 스크립트

아래 스크립트를 `test_local.py`로 저장하고 로컬에서 실행하면
MCP 서버 없이도 각 단계를 독립적으로 검증할 수 있습니다.

```bash
cd ~/Documents/since/brawl-and-build
source venv/bin/activate
python test_local.py
```

```python
#!/usr/bin/env python3
"""Brawl & Build 로컬 검증 스크립트.

MCP 서버를 거치지 않고 각 모듈을 직접 호출하여 테스트합니다.
전체 실행 또는 개별 단계만 선택 가능합니다.

Usage:
    python test_local.py                  # 전체 진단
    python test_local.py --step env       # 환경만 검사
    python test_local.py --step github    # GitHub 연결만 검사
    python test_local.py --step discuss   # 토론만 실행
    python test_local.py --step build     # 코드 생성만 실행
    python test_local.py --step pr        # PR 생성만 실행
"""

import argparse
import json
import os
import re
import subprocess
import sys
import time
from hashlib import md5
from pathlib import Path

# ── 프로젝트 루트를 path에 추가 ──
ROOT = Path(__file__).parent
sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv
load_dotenv(ROOT / ".env")


# ═══════════════════════════════════════
#  공통 유틸
# ═══════════════════════════════════════

GREEN = "\033[92m"
RED = "\033[91m"
YELLOW = "\033[93m"
CYAN = "\033[96m"
RESET = "\033[0m"
BOLD = "\033[1m"

def ok(msg):   print(f"  {GREEN}✔{RESET} {msg}")
def fail(msg): print(f"  {RED}✘{RESET} {msg}")
def warn(msg): print(f"  {YELLOW}⚠{RESET} {msg}")
def info(msg): print(f"  {CYAN}ℹ{RESET} {msg}")
def header(msg): print(f"\n{BOLD}{'═'*50}\n  {msg}\n{'═'*50}{RESET}")


# ═══════════════════════════════════════
#  Step 1: 환경 검사
# ═══════════════════════════════════════

def check_env():
    header("Step 1: 환경 검사")
    errors = []

    # Python 패키지
    packages = ["langchain", "langchain_anthropic", "langgraph", "mcp", "requests", "dotenv"]
    for pkg in packages:
        try:
            __import__(pkg)
            ok(f"{pkg} 설치됨")
        except ImportError:
            fail(f"{pkg} 미설치")
            errors.append(pkg)

    # 환경 변수
    anthropic_key = os.environ.get("ANTHROPIC_API_KEY", "")
    github_token = os.environ.get("GITHUB_TOKEN", "")

    if anthropic_key and anthropic_key.startswith("sk-ant-"):
        ok(f"ANTHROPIC_API_KEY 설정됨 ({anthropic_key[:12]}...)")
    else:
        fail("ANTHROPIC_API_KEY 미설정 또는 잘못된 형식")
        errors.append("ANTHROPIC_API_KEY")

    if github_token and github_token.startswith("ghp_"):
        ok(f"GITHUB_TOKEN 설정됨 ({github_token[:8]}...)")
    else:
        fail("GITHUB_TOKEN 미설정 또는 잘못된 형식")
        errors.append("GITHUB_TOKEN")

    # CLI 도구
    for tool in ["git", "node", "npx"]:
        proc = subprocess.run(["which", tool], capture_output=True, text=True)
        if proc.returncode == 0:
            ok(f"{tool} → {proc.stdout.strip()}")
        else:
            fail(f"{tool} 미설치")
            errors.append(tool)

    if errors:
        fail(f"환경 문제 {len(errors)}건: {', '.join(errors)}")
    else:
        ok("환경 검사 통과!")
    return len(errors) == 0


# ═══════════════════════════════════════
#  Step 2: GitHub 연결 검사
# ═══════════════════════════════════════

def check_github(target_path=None):
    header("Step 2: GitHub 연결 검사")
    token = os.environ.get("GITHUB_TOKEN", "")
    errors = []

    if not token:
        fail("GITHUB_TOKEN 없음 — skip")
        return False

    import requests

    # 토큰 유효성
    resp = requests.get(
        "https://api.github.com/user",
        headers={"Authorization": f"token {token}"},
        timeout=10,
    )
    if resp.status_code == 200:
        user = resp.json()
        ok(f"GitHub 인증 성공: {user['login']} ({user.get('name', '')})")
    else:
        fail(f"GitHub 인증 실패: HTTP {resp.status_code}")
        errors.append("auth")

    # 토큰 권한 (scopes)
    scopes = resp.headers.get("X-OAuth-Scopes", "")
    if "repo" in scopes:
        ok(f"토큰 권한: {scopes}")
    else:
        warn(f"토큰 권한에 'repo' 없음: {scopes}")
        warn("PR 생성에 'repo' 권한이 필요합니다")
        errors.append("scope")

    # target repo 확인
    if target_path:
        proc = subprocess.run(
            ["git", "remote", "get-url", "origin"],
            cwd=target_path, capture_output=True, text=True,
        )
        url = proc.stdout.strip()
        match = re.search(r'github\.com[:/]([^/]+)/([^/.]+)', url)
        if match:
            owner, repo = match.group(1), match.group(2)
            ok(f"Target repo: {owner}/{repo}")

            # repo 접근 가능한지
            resp = requests.get(
                f"https://api.github.com/repos/{owner}/{repo}",
                headers={"Authorization": f"token {token}"},
                timeout=10,
            )
            if resp.status_code == 200:
                ok(f"Repo 접근 OK (private={resp.json().get('private', False)})")
            else:
                fail(f"Repo 접근 실패: HTTP {resp.status_code}")
                errors.append("repo_access")
        else:
            fail(f"Remote URL 파싱 실패: {url}")
            errors.append("remote_url")

    if errors:
        fail(f"GitHub 문제 {len(errors)}건")
    else:
        ok("GitHub 검사 통과!")
    return len(errors) == 0


# ═══════════════════════════════════════
#  Step 3: 토론 실행 테스트
# ═══════════════════════════════════════

def test_discuss(target_path=None):
    header("Step 3: 토론 실행 (discuss)")

    from core.graph import run_discussion
    from core.exporter import state_to_result, export_markdown
    from core.cost_tracker import track_cost

    project = "테스트 프로젝트"
    feature = "사용자 로그인"
    previous_context = ""

    if target_path:
        from core.project_config import load_config, build_previous_context
        config = load_config(target_path)
        if config:
            project = config.project
            previous_context = build_previous_context(target_path)
            info(f"프로젝트: {project}")
            if previous_context:
                info(f"이전 토론 컨텍스트 로드됨 ({len(previous_context)}자)")

    info(f"토론 시작: '{feature}' (1라운드, build=False)")
    start = time.time()

    try:
        with track_cost() as tracker:
            final_state = run_discussion(
                project_description=project,
                feature_name=feature,
                feature_description="이메일/비밀번호 기반 로그인",
                max_rounds=1,  # 테스트는 1라운드만
                enable_build=False,
            )

        elapsed = time.time() - start
        result = state_to_result(final_state)

        ok(f"토론 완료 ({elapsed:.1f}s)")
        info(f"결정사항: {len(result.decisions)}건")
        for d in result.decisions[:3]:
            info(f"  - {d[:60]}...")
        info(f"미해결: {len(result.unresolved)}건")
        info(f"비용: {tracker.to_dict()}")

        # 파일 저장
        out_dir = os.path.join(target_path, "docs", "discussions") if target_path else "output"
        md_path = export_markdown(result, output_dir=out_dir)
        ok(f"토론 결과 저장: {md_path}")
        return True

    except Exception as e:
        fail(f"토론 실패: {e}")
        import traceback
        traceback.print_exc()
        return False


# ═══════════════════════════════════════
#  Step 4: 코드 생성 테스트
# ═══════════════════════════════════════

def test_build(target_path=None):
    header("Step 4: 코드 생성 (build_code)")

    from core.graph import run_discussion
    from core.exporter import state_to_result
    from core.code_generator import save_generated_code
    from core.cost_tracker import track_cost

    project = "테스트 프로젝트"
    feature = "사용자 로그인"
    previous_context = ""

    if target_path:
        from core.project_config import load_config, build_previous_context
        config = load_config(target_path)
        if config:
            project = config.project
            previous_context = build_previous_context(target_path)

    info(f"토론 + 코드 생성 시작: '{feature}' (1라운드)")
    start = time.time()

    try:
        with track_cost() as tracker:
            final_state = run_discussion(
                project_description=project,
                feature_name=feature,
                feature_description="이메일/비밀번호 기반 로그인",
                max_rounds=1,
                enable_build=True,  # Build Phase 포함
                previous_context=previous_context,
            )

        elapsed = time.time() - start
        result = state_to_result(final_state)
        ok(f"토론 + 코드 생성 완료 ({elapsed:.1f}s)")

        # 코드 저장
        code_dir = target_path if target_path else "generated"
        saved_files = save_generated_code(final_state, output_dir=code_dir)
        ok(f"저장된 파일 {len(saved_files)}개:")
        for f in saved_files:
            info(f"  {f}")

        info(f"비용: {tracker.to_dict()}")
        return True

    except Exception as e:
        fail(f"코드 생성 실패: {e}")
        import traceback
        traceback.print_exc()
        return False


# ═══════════════════════════════════════
#  Step 5: PR 생성 테스트
# ═══════════════════════════════════════

def test_pr(target_path):
    header("Step 5: PR 생성 (create_pr)")

    if not target_path:
        fail("target_path 필요 (--target 옵션)")
        return False

    import requests
    token = os.environ.get("GITHUB_TOKEN", "")
    if not token:
        fail("GITHUB_TOKEN 없음")
        return False

    feature = "사용자 로그인"
    slug = md5(feature.encode()).hexdigest()[:8]
    branch_name = f"feature/{slug}"

    # owner/repo 추출
    proc = subprocess.run(
        ["git", "remote", "get-url", "origin"],
        cwd=target_path, capture_output=True, text=True,
    )
    match = re.search(r'github\.com[:/]([^/]+)/([^/.]+)', proc.stdout.strip())
    if not match:
        fail("GitHub remote URL 파싱 실패")
        return False
    owner, repo = match.group(1), match.group(2)
    info(f"Repo: {owner}/{repo}")
    info(f"Branch: {branch_name}")

    try:
        # git 상태 확인
        proc = subprocess.run(
            ["git", "status", "--porcelain"],
            cwd=target_path, capture_output=True, text=True,
        )
        changes = proc.stdout.strip()
        if not changes:
            warn("변경사항이 없습니다. 커밋할 내용이 없어 PR 테스트를 건너뜁니다.")
            info("build_code를 먼저 실행하여 코드를 생성하세요.")
            return True

        info(f"변경 파일 {len(changes.splitlines())}개")

        # 기존 브랜치 삭제
        subprocess.run(
            ["git", "branch", "-D", branch_name],
            cwd=target_path, capture_output=True, text=True,
        )

        # 브랜치 생성 + 커밋
        cmds = [
            ["git", "checkout", "-b", branch_name],
            ["git", "add", "."],
            ["git", "commit", "-m", f"feat: {feature} scaffold by brawl-and-build"],
        ]
        for cmd in cmds:
            proc = subprocess.run(cmd, cwd=target_path, capture_output=True, text=True)
            if proc.returncode != 0 and "nothing to commit" not in proc.stdout:
                fail(f"실패: {' '.join(cmd)}\n    {proc.stderr.strip()}")
                return False
            ok(f"{' '.join(cmd[:3])}...")

        # push (토큰 인증)
        push_url = f"https://x-access-token:{token}@github.com/{owner}/{repo}.git"
        proc = subprocess.run(
            ["git", "push", "-u", push_url, branch_name, "--force"],
            cwd=target_path, capture_output=True, text=True, timeout=60,
        )
        if proc.returncode != 0:
            fail(f"push 실패: {proc.stderr.replace(token, '***')}")
            return False
        ok("git push 성공")

        # PR 생성
        headers = {
            "Authorization": f"token {token}",
            "Accept": "application/vnd.github.v3+json",
        }
        pr_data = {
            "title": f"feat: {feature}",
            "body": f"## feat: {feature}\n\n테스트 PR입니다.\n\n---\n*Generated by Brawl & Build*",
            "head": branch_name,
            "base": "main",
        }
        resp = requests.post(
            f"https://api.github.com/repos/{owner}/{repo}/pulls",
            json=pr_data, headers=headers, timeout=30,
        )
        if resp.status_code == 201:
            pr_url = resp.json()["html_url"]
            ok(f"PR 생성 성공: {pr_url}")
        elif resp.status_code == 422:
            warn("PR이 이미 존재합니다 (정상)")
        else:
            fail(f"PR 생성 실패: HTTP {resp.status_code} — {resp.text[:200]}")
            return False

        return True

    except Exception as e:
        fail(f"PR 테스트 실패: {e}")
        import traceback
        traceback.print_exc()
        return False


# ═══════════════════════════════════════
#  MCP 서버 직접 로드 테스트
# ═══════════════════════════════════════

def test_mcp_load():
    header("Bonus: MCP 서버 로드 검사")

    try:
        # mcp_server.py를 import하여 문법 + 의존성 확인
        import importlib.util
        spec = importlib.util.spec_from_file_location("mcp_server", ROOT / "mcp_server.py")
        mod = importlib.util.module_from_spec(spec)

        # 실제 서버 시작은 하지 않고 로드만 테스트
        # (FastMCP.run()은 __name__ == "__main__" 가드 안에 있으므로 안전)
        spec.loader.exec_module(mod)

        # 등록된 도구 확인
        tools = list(mod.mcp._tool_manager._tools.keys()) if hasattr(mod.mcp, '_tool_manager') else []
        if tools:
            ok(f"MCP 도구 {len(tools)}개 등록: {', '.join(tools)}")
        else:
            # FastMCP 버전에 따라 내부 구조가 다를 수 있음
            info("MCP 도구 목록 확인 불가 (서버 로드 자체는 성공)")

        ok("mcp_server.py 로드 성공 (문법, 의존성 OK)")
        return True

    except Exception as e:
        fail(f"mcp_server.py 로드 실패: {e}")
        import traceback
        traceback.print_exc()
        return False


# ═══════════════════════════════════════
#  메인
# ═══════════════════════════════════════

def main():
    parser = argparse.ArgumentParser(description="Brawl & Build 로컬 테스트")
    parser.add_argument(
        "--step",
        choices=["env", "github", "discuss", "build", "pr", "mcp", "all"],
        default="all",
        help="실행할 테스트 단계 (기본: all = 환경 + GitHub + MCP 로드)",
    )
    parser.add_argument(
        "--target",
        default=None,
        help="대상 프로젝트 경로 (예: ~/Documents/since/brawl-test-repo)",
    )
    parser.add_argument(
        "--full",
        action="store_true",
        help="discuss, build, pr 포함 전체 실행 (API 비용 발생!)",
    )
    args = parser.parse_args()

    target = os.path.expanduser(args.target) if args.target else None

    print(f"\n{BOLD}🥊 Brawl & Build — 로컬 테스트{RESET}")
    print(f"   엔진: {ROOT}")
    if target:
        print(f"   타겟: {target}")

    results = {}

    if args.step in ("env", "all"):
        results["env"] = check_env()

    if args.step in ("github", "all"):
        results["github"] = check_github(target)

    if args.step in ("mcp", "all"):
        results["mcp"] = test_mcp_load()

    if args.step == "discuss" or args.full:
        results["discuss"] = test_discuss(target)

    if args.step == "build" or args.full:
        results["build"] = test_build(target)

    if args.step == "pr":
        results["pr"] = test_pr(target)

    # 요약
    header("테스트 결과 요약")
    for step, passed in results.items():
        status = f"{GREEN}PASS{RESET}" if passed else f"{RED}FAIL{RESET}"
        print(f"  {step:12s} {status}")

    total = len(results)
    passed = sum(1 for v in results.values() if v)
    print(f"\n  {passed}/{total} 통과")

    if passed < total:
        print(f"\n  {YELLOW}실패한 단계를 해결한 후 다시 실행하세요.{RESET}")
        print(f"  개별 실행: python test_local.py --step <step>")
        sys.exit(1)
    else:
        print(f"\n  {GREEN}모든 테스트 통과! Claude Desktop에서 시연 준비 완료.{RESET}")


if __name__ == "__main__":
    main()
```
