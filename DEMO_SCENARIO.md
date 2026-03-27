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

| 증상 | 원인 | 해결 |
|------|------|------|
| `GITHUB_TOKEN이 설정되지 않았습니다` | .env 또는 MCP env 누락 | `.env`에 토큰 추가 후 Claude Desktop 재시작 |
| `discuss` 호출 후 응답 없음 | ANTHROPIC_API_KEY 문제 | `.env` 키 확인 |
| scaffold timeout | npm registry 느림 | 재시도 또는 `--init` 따로 실행 |
| `branch already exists` | 같은 feature로 재실행 | 자동 처리됨 (기존 브랜치 삭제 후 재생성) |
| `get_task_status` not_found | 서버 재시작으로 task 유실 | discuss/build_code 다시 실행 |

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
