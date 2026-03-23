"""Build 페이즈 - 토론 결정사항을 기반으로 코드를 생성합니다.

출력 구조 (Lerna 모노레포):
  generated/
  ├── package.json          (lerna root)
  ├── lerna.json
  ├── packages/
  │   ├── backend/          (NestJS)
  │   │   ├── src/
  │   │   │   ├── <feature>/
  │   │   │   │   ├── <feature>.controller.ts
  │   │   │   │   ├── <feature>.service.ts
  │   │   │   │   ├── <feature>.module.ts
  │   │   │   │   ├── dto/
  │   │   │   │   └── entities/
  │   │   │   └── ...
  │   │   └── package.json
  │   └── frontend/         (React + TypeScript)
  │       ├── src/
  │       │   ├── components/<Feature>/
  │       │   ├── hooks/
  │       │   ├── types/
  │       │   └── api/
  │       └── package.json
  └── packages/shared/      (공유 타입)
      └── src/types/
"""

import os
import json
from langchain_anthropic import ChatAnthropic
from langchain_core.messages import HumanMessage, SystemMessage
from core.state import DiscussionState
from core.cost_tracker import get_tracker


# ── 코드 생성 시스템 프롬프트 ──

BE_CODE_PROMPT = """당신은 NestJS 백엔드 시니어 개발자입니다.
토론에서 결정된 사항을 바탕으로 실제 NestJS 코드를 생성하세요.

규칙:
- TypeScript 사용
- NestJS + TypeORM 패턴
- class-validator를 사용한 DTO 검증
- 코드에 한글 주석으로 설명 포함
- 각 파일은 ```typescript filename="경로/파일명.ts" 블록으로 구분

생성할 파일:
1. <feature>.controller.ts - API 엔드포인트
2. <feature>.service.ts - 비즈니스 로직
3. <feature>.module.ts - 모듈 정의
4. dto/create-<feature>.dto.ts - 생성 DTO
5. dto/update-<feature>.dto.ts - 수정 DTO
6. entities/<feature>.entity.ts - TypeORM 엔티티"""

FE_CODE_PROMPT = """당신은 React + TypeScript 프론트엔드 시니어 개발자입니다.
토론에서 결정된 사항을 바탕으로 실제 React 코드를 생성하세요.

규칙:
- TypeScript 사용
- 함수형 컴포넌트 + Hooks
- API 호출은 커스텀 hook으로 분리
- 타입 정의는 별도 파일로 분리
- 코드에 한글 주석으로 설명 포함
- 각 파일은 ```typescript filename="경로/파일명.ts" 또는 ```tsx filename="경로/파일명.tsx" 블록으로 구분

생성할 파일:
1. components/<Feature>/<Feature>.tsx - 메인 컴포넌트
2. components/<Feature>/<Feature>Form.tsx - 폼 컴포넌트 (필요시)
3. hooks/use<Feature>.ts - 커스텀 훅 (API 호출 포함)
4. types/<feature>.types.ts - 타입 정의
5. api/<feature>.api.ts - API 클라이언트"""

SHARED_TYPE_PROMPT = """당신은 풀스택 개발자입니다.
토론에서 결정된 사항을 바탕으로 프론트엔드와 백엔드가 공유하는 타입 정의를 생성하세요.

규칙:
- TypeScript 사용
- interface 위주로 정의
- API 요청/응답 타입 포함
- 각 파일은 ```typescript filename="경로/파일명.ts" 블록으로 구분

생성할 파일:
1. types/<feature>.types.ts - 공유 타입/인터페이스
2. types/api-response.types.ts - 공통 API 응답 타입"""

API_SPEC_PROMPT = """당신은 PM이자 API 설계자입니다.
토론에서 결정된 사항을 바탕으로 OpenAPI(Swagger) YAML 명세를 생성하세요.

규칙:
- OpenAPI 3.0 형식
- 각 엔드포인트에 한글 설명 포함
- 요청/응답 스키마 포함
- 에러 응답 포함

```yaml filename="api-spec/<feature>.openapi.yaml" 블록으로 출력하세요."""


def create_build_node(
    role: str,
    model: str = "claude-sonnet-4-20250514",
):
    """코드 생성 노드를 만듭니다.

    role: "be", "fe", "shared", "api_spec"
    """

    llm = ChatAnthropic(model=model, max_tokens=4096)

    system_prompts = {
        "be": BE_CODE_PROMPT,
        "fe": FE_CODE_PROMPT,
        "shared": SHARED_TYPE_PROMPT,
        "api_spec": API_SPEC_PROMPT,
    }

    def build_node(state: DiscussionState) -> dict:
        # 토론 결과를 컨텍스트로
        decisions = state.get("decisions", [])
        summary = state.get("summary", "")
        discussion_log = state.get("discussion_log", [])

        # 최근 토론 내용 요약 (컨텍스트 절약)
        recent_discussion = _summarize_discussion_for_build(discussion_log)

        prompt = f"""## 프로젝트: {state["project_description"]}
## 기능: {state["feature_name"]}
{f'## 기능 설명: {state["feature_description"]}' if state.get("feature_description") else ""}

## 토론에서 결정된 사항:
{chr(10).join(f"- {d}" for d in decisions)}

## 토론 요약:
{summary}

## 주요 토론 내용:
{recent_discussion}

위 내용을 바탕으로 코드를 생성하세요. 모노레포 구조(Lerna)에 맞게 경로를 지정하세요.
- 백엔드: packages/backend/src/
- 프론트엔드: packages/frontend/src/
- 공유: packages/shared/src/"""

        response = llm.invoke([
            SystemMessage(content=system_prompts[role]),
            HumanMessage(content=prompt),
        ])

        get_tracker().track(response, model=model)

        # 생성된 코드를 build_outputs에 누적
        build_outputs = state.get("build_outputs", [])
        build_outputs.append({
            "role": role,
            "content": response.content,
        })

        return {
            "build_outputs": build_outputs,
            "messages": [response],
        }

    return build_node


def save_generated_code(state: DiscussionState, output_dir: str = "generated") -> list[str]:
    """LLM 응답에서 코드 블록을 추출하여 파일로 저장합니다."""

    build_outputs = state.get("build_outputs", [])
    saved_files = []

    # Lerna 루트 설정 파일 생성
    _create_monorepo_scaffold(output_dir)

    for output in build_outputs:
        content = output["content"]
        files = _extract_code_blocks(content)

        for filepath, code in files:
            full_path = os.path.join(output_dir, filepath)
            os.makedirs(os.path.dirname(full_path), exist_ok=True)

            with open(full_path, "w", encoding="utf-8") as f:
                f.write(code)

            saved_files.append(full_path)

    return saved_files


def _extract_code_blocks(content: str) -> list[tuple[str, str]]:
    """마크다운 코드 블록에서 filename과 코드를 추출합니다.

    형식: ```typescript filename="path/to/file.ts"
    """
    files = []
    lines = content.split("\n")
    i = 0

    while i < len(lines):
        line = lines[i]

        if line.strip().startswith("```") and 'filename="' in line:
            # filename 추출
            start = line.index('filename="') + len('filename="')
            end = line.index('"', start)
            filename = line[start:end]

            # 코드 본문 수집
            code_lines = []
            i += 1
            while i < len(lines) and not lines[i].strip().startswith("```"):
                code_lines.append(lines[i])
                i += 1

            files.append((filename, "\n".join(code_lines)))

        i += 1

    return files


def _create_monorepo_scaffold(output_dir: str):
    """Lerna 모노레포 기본 구조를 생성합니다."""

    os.makedirs(output_dir, exist_ok=True)

    # lerna.json
    lerna_config = {
        "$schema": "https://json.schemastore.org/lerna.json",
        "version": "0.1.0",
        "packages": ["packages/*"],
    }
    with open(os.path.join(output_dir, "lerna.json"), "w") as f:
        json.dump(lerna_config, f, indent=2)

    # root package.json
    root_pkg = {
        "name": "brawl-and-build-generated",
        "private": True,
        "workspaces": ["packages/*"],
        "devDependencies": {
            "lerna": "^8.0.0",
        },
    }
    with open(os.path.join(output_dir, "package.json"), "w") as f:
        json.dump(root_pkg, f, indent=2)

    # backend package.json
    be_dir = os.path.join(output_dir, "packages", "backend")
    os.makedirs(os.path.join(be_dir, "src"), exist_ok=True)
    be_pkg = {
        "name": "@brawl-and-build/backend",
        "version": "0.1.0",
        "dependencies": {
            "@nestjs/common": "^10.0.0",
            "@nestjs/core": "^10.0.0",
            "@nestjs/typeorm": "^10.0.0",
            "typeorm": "^0.3.0",
            "class-validator": "^0.14.0",
            "class-transformer": "^0.5.0",
        },
    }
    with open(os.path.join(be_dir, "package.json"), "w") as f:
        json.dump(be_pkg, f, indent=2)

    # frontend package.json
    fe_dir = os.path.join(output_dir, "packages", "frontend")
    os.makedirs(os.path.join(fe_dir, "src"), exist_ok=True)
    fe_pkg = {
        "name": "@brawl-and-build/frontend",
        "version": "0.1.0",
        "dependencies": {
            "react": "^18.0.0",
            "react-dom": "^18.0.0",
            "axios": "^1.6.0",
        },
        "devDependencies": {
            "@types/react": "^18.0.0",
            "typescript": "^5.0.0",
        },
    }
    with open(os.path.join(fe_dir, "package.json"), "w") as f:
        json.dump(fe_pkg, f, indent=2)

    # shared package.json
    shared_dir = os.path.join(output_dir, "packages", "shared")
    os.makedirs(os.path.join(shared_dir, "src", "types"), exist_ok=True)
    shared_pkg = {
        "name": "@brawl-and-build/shared",
        "version": "0.1.0",
        "main": "src/index.ts",
        "devDependencies": {
            "typescript": "^5.0.0",
        },
    }
    with open(os.path.join(shared_dir, "package.json"), "w") as f:
        json.dump(shared_pkg, f, indent=2)


def _summarize_discussion_for_build(discussion_log: list[dict]) -> str:
    """Build용으로 토론 내용을 간결하게 요약합니다."""
    if not discussion_log:
        return "(토론 내용 없음)"

    # 마지막 라운드의 PM wrap_up 위주로 + 핵심 발언
    lines = []
    last_round = max(e["round"] for e in discussion_log)

    for entry in discussion_log:
        if entry["round"] == last_round:
            lines.append(f"[{entry['role']}]: {entry['content']}")
        elif "wrap_up" in entry.get("role", "") or "kickoff" in entry.get("role", ""):
            lines.append(f"[{entry['role']}]: {entry['content']}")

    return "\n\n".join(lines[-8:])  # 최대 8개만
