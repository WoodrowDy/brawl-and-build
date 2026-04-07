"""Build 페이즈 - 토론 결정사항을 기반으로 코드를 생성합니다.

방식: CLI scaffold → LLM 기능 코드 생성
  1단계: nest new, create-vite 로 완전한 프로젝트 구조 생성
  2단계: LLM은 기능 코드(controller, service, component 등)만 생성
  3단계: 보일러플레이트 정리

출력 구조 (Lerna 모노레포):
  target/
  ├── package.json          (lerna root)
  ├── lerna.json
  ├── packages/
  │   ├── backend/          (NestJS - nest new로 생성)
  │   ├── frontend/         (React+Vite - create-vite로 생성)
  │   └── shared/           (공유 타입)
"""

import os
import json
import subprocess
import shutil
from langchain_core.messages import HumanMessage, SystemMessage
from core.state import DiscussionState
from core.cost_tracker import get_tracker


# ══════════════════════════════════════════
#  시스템 프롬프트 (기능 코드에만 집중)
# ══════════════════════════════════════════

BE_CODE_PROMPT = """당신은 NestJS 백엔드 시니어 개발자입니다.
토론에서 결정된 사항을 바탕으로 기능 코드를 생성하세요.

**중요**: 프로젝트 구조(main.ts, app.module.ts, tsconfig 등)는 이미 nest CLI로 생성되어 있습니다.
당신은 기능 모듈 파일만 생성하면 됩니다.

규칙:
- TypeScript strict 모드
- NestJS + TypeORM 패턴
- class-validator를 사용한 DTO 검증
- 코드에 한글 주석으로 설명 포함
- 각 파일은 ```typescript filename="경로/파일명.ts" 블록으로 구분
- import 경로는 packages/backend/src/ 내부 상대경로

**반드시** 아래 파일을 모두 생성하세요:

1. packages/backend/src/<feature>/<feature>.module.ts - 기능 모듈 정의 (TypeOrmModule.forFeature 포함)
2. packages/backend/src/<feature>/<feature>.controller.ts - API 엔드포인트
3. packages/backend/src/<feature>/<feature>.service.ts - 비즈니스 로직
4. packages/backend/src/<feature>/dto/ - 요청 DTO (class-validator 데코레이터)
5. packages/backend/src/<feature>/entities/ - TypeORM 엔티티

추가로, 기존 app.module.ts에 이 모듈을 어떻게 import해야 하는지 주석으로 안내하세요.
(예: `// app.module.ts의 imports 배열에 AuthModule을 추가하세요`)

모든 import가 정상 작동하도록 모듈 간 의존성을 정확히 맞추세요."""

FE_CODE_PROMPT = """당신은 React + TypeScript 프론트엔드 시니어 개발자입니다.
토론에서 결정된 사항을 바탕으로 기능 코드를 생성하세요.

**중요**: 프로젝트 구조(main.tsx, App.tsx, vite.config 등)는 이미 create-vite로 생성되어 있습니다.
당신은 기능 관련 파일만 생성하면 됩니다.

규칙:
- TypeScript strict 모드
- 함수형 컴포넌트 + Hooks
- API 호출은 커스텀 hook으로 분리
- 공유 타입은 @brawl-and-build/shared 에서 import
- 코드에 한글 주석으로 설명 포함
- 각 파일은 ```typescript filename="경로/파일명.ts" 또는 ```tsx filename="경로/파일명.tsx" 블록으로 구분

**반드시** 아래 파일을 모두 생성하세요:

1. packages/frontend/src/components/<Feature>/<Feature>.tsx - 메인 컴포넌트
2. packages/frontend/src/components/<Feature>/<Feature>Form.tsx - 폼 컴포넌트 (필요시)
3. packages/frontend/src/hooks/use<Feature>.ts - 커스텀 훅 (API 호출, 상태 관리)
4. packages/frontend/src/api/<feature>.api.ts - Axios API 클라이언트 (baseURL 설정)
5. packages/frontend/src/stores/<feature>Store.ts - 상태 관리 (zustand 또는 context)

추가로, 기존 App.tsx에 이 컴포넌트를 어떻게 라우팅해야 하는지 주석으로 안내하세요.
(예: `// App.tsx에 <Route path="/login" element={<LoginPage />} /> 추가`)

모든 컴포넌트가 정상 렌더링되도록 import/export를 정확히 맞추세요."""

SHARED_TYPE_PROMPT = """당신은 풀스택 개발자입니다.
토론에서 결정된 사항을 바탕으로 프론트엔드와 백엔드가 공유하는 타입 정의를 생성하세요.

규칙:
- TypeScript strict 모드
- interface 위주로 정의
- API 요청/응답 타입 포함
- 각 파일은 ```typescript filename="경로/파일명.ts" 블록으로 구분

**반드시** 아래 파일을 모두 생성하세요:
1. packages/shared/src/types/<feature>.types.ts - 기능별 공유 타입/인터페이스
2. packages/shared/src/types/api-response.types.ts - 공통 API 응답 래퍼 타입
3. packages/shared/src/index.ts - 모든 타입을 re-export하는 엔트리포인트

index.ts에서 모든 타입 파일을 export * from './types/...' 형태로 내보내세요."""

API_SPEC_PROMPT = """당신은 PM이자 API 설계자입니다.
토론에서 결정된 사항을 바탕으로 OpenAPI(Swagger) YAML 명세를 생성하세요.

규칙:
- OpenAPI 3.0 형식
- 각 엔드포인트에 한글 설명 포함
- 요청/응답 스키마 포함
- 에러 응답 포함

```yaml filename="api-spec/<feature>.openapi.yaml" 블록으로 출력하세요."""


# ══════════════════════════════════════════
#  LLM 코드 생성 노드
# ══════════════════════════════════════════

def create_build_node(
    role: str,
    llm,
    model: str = "claude-sonnet-4-20250514",
):
    """코드 생성 노드를 만듭니다.

    role: "be", "fe", "shared", "api_spec"
    """

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

위 내용을 바탕으로 기능 코드를 생성하세요.
프로젝트 구조(main.ts, App.tsx, tsconfig 등)는 이미 CLI로 생성되어 있으니 기능 파일만 만드세요.
- 백엔드: packages/backend/src/
- 프론트엔드: packages/frontend/src/
- 공유: packages/shared/src/"""

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


# ══════════════════════════════════════════
#  코드 저장
# ══════════════════════════════════════════

def scaffold_project(output_dir: str) -> dict:
    """프로젝트 초기 scaffold를 실행합니다.

    init_project 시점에 한 번만 호출됩니다.
    nest new, create-vite 로 완전한 프로젝트 구조를 생성합니다.
    """
    return _create_monorepo_scaffold(output_dir)


def save_generated_code(state: DiscussionState, output_dir: str = "generated") -> list[str]:
    """LLM 응답에서 기능 코드를 추출하여 파일로 저장합니다.

    scaffold는 init_project에서 이미 완료된 상태.
    여기서는 기능 코드 저장 + app.module.ts 패치만 수행합니다.
    """

    build_outputs = state.get("build_outputs", [])
    saved_files = []

    # scaffold가 안 되어 있으면 fallback으로 실행
    be_main = os.path.join(output_dir, "packages", "backend", "src", "main.ts")
    if not os.path.exists(be_main):
        _create_monorepo_scaffold(output_dir)

    # LLM 코드 저장
    for output in build_outputs:
        content = output["content"]
        files = _extract_code_blocks(content)

        for filepath, code in files:
            full_path = os.path.join(output_dir, filepath)
            os.makedirs(os.path.dirname(full_path), exist_ok=True)

            with open(full_path, "w", encoding="utf-8") as f:
                f.write(code)

            saved_files.append(full_path)

    # 3단계: app.module.ts 패치 (기능 모듈 자동 import)
    _patch_app_module(output_dir, state.get("feature_name", ""))

    return saved_files


# ══════════════════════════════════════════
#  CLI Scaffold (핵심 변경점)
# ══════════════════════════════════════════

def _get_env() -> dict:
    """subprocess에 전달할 환경변수 (PATH 보강)."""
    env = os.environ.copy()
    extra_paths = [
        "/opt/homebrew/bin",
        "/usr/local/bin",
        os.path.expanduser("~/.nvm/versions/node/v20.12.2/bin"),
        os.path.expanduser("~/.nvm/versions/node/v24.12.0/bin"),
    ]
    env["PATH"] = ":".join(extra_paths) + ":" + env.get("PATH", "")
    return env


def _run_cmd(cmd: list[str], cwd: str, timeout: int = 120) -> subprocess.CompletedProcess:
    """subprocess 실행 헬퍼."""
    return subprocess.run(
        cmd, cwd=cwd, env=_get_env(),
        capture_output=True, text=True, timeout=timeout,
    )


def _create_monorepo_scaffold(output_dir: str) -> dict:
    """Lerna 모노레포 + CLI scaffold로 프로젝트 구조를 생성합니다.

    이미 packages/backend/src/main.ts 등이 존재하면 skip합니다.
    """
    result = {"created_files": [], "skipped": False}
    os.makedirs(output_dir, exist_ok=True)

    packages_dir = os.path.join(output_dir, "packages")
    be_dir = os.path.join(packages_dir, "backend")
    fe_dir = os.path.join(packages_dir, "frontend")
    shared_dir = os.path.join(packages_dir, "shared")

    # ── 이미 scaffold 되어 있으면 skip ──
    if os.path.exists(os.path.join(be_dir, "src", "main.ts")):
        result["skipped"] = True
        return result

    os.makedirs(packages_dir, exist_ok=True)

    # ── 루트 설정 ──
    _write_json(output_dir, "lerna.json", {
        "$schema": "https://json.schemastore.org/lerna.json",
        "version": "0.1.0",
        "packages": ["packages/*"],
    })

    _write_json(output_dir, "package.json", {
        "name": "brawl-and-build-generated",
        "private": True,
        "workspaces": ["packages/*"],
        "scripts": {
            "dev:backend": "cd packages/backend && npm run start:dev",
            "dev:frontend": "cd packages/frontend && npm run dev",
            "build": "lerna run build",
        },
        "devDependencies": {
            "lerna": "^8.0.0",
        },
    })

    _write_file(output_dir, ".gitignore", """node_modules/
dist/
.env
*.js.map
*.d.ts.map
.DS_Store
""")

    _write_file(output_dir, ".env.example", """# Backend
DATABASE_HOST=localhost
DATABASE_PORT=5432
DATABASE_NAME=mydb
DATABASE_USER=postgres
DATABASE_PASSWORD=postgres
JWT_SECRET=your-jwt-secret-change-me
JWT_REFRESH_SECRET=your-refresh-secret-change-me
REDIS_HOST=localhost
REDIS_PORT=6379

# Frontend
VITE_API_URL=http://localhost:3000
""")

    # ── Backend: nest new ──
    _scaffold_backend(packages_dir, be_dir)

    # ── Frontend: create-vite ──
    _scaffold_frontend(packages_dir, fe_dir)

    # ── Shared: 수동 생성 (CLI 없음) ──
    _scaffold_shared(shared_dir)

    return result


def _scaffold_backend(packages_dir: str, be_dir: str):
    """nest CLI로 NestJS 프로젝트를 생성합니다."""

    try:
        proc = _run_cmd(
            ["npx", "--yes", "@nestjs/cli", "new", "backend",
             "--skip-git", "--package-manager", "npm", "--strict"],
            cwd=packages_dir,
            timeout=180,
        )
    except subprocess.TimeoutExpired:
        proc = None

    if proc and proc.returncode == 0 and os.path.exists(os.path.join(be_dir, "src", "main.ts")):
        # nest CLI 성공 → 추가 의존성 설치
        _run_cmd(
            ["npm", "install",
             "@nestjs/config", "@nestjs/jwt", "@nestjs/passport",
             "@nestjs/typeorm", "@nestjs/throttler",
             "typeorm", "pg", "bcrypt",
             "passport", "passport-jwt",
             "class-validator", "class-transformer"],
            cwd=be_dir,
        )
        _run_cmd(
            ["npm", "install", "-D",
             "@types/bcrypt", "@types/passport-jwt"],
            cwd=be_dir,
        )

        # 불필요한 보일러플레이트 정리
        _cleanup_nest_boilerplate(be_dir)

        # package.json name 수정
        _patch_package_name(be_dir, "@brawl-and-build/backend")
    else:
        # nest CLI 실패 시 fallback → 수동 생성
        _scaffold_backend_fallback(be_dir)


def _scaffold_frontend(packages_dir: str, fe_dir: str):
    """create-vite로 React+TS 프로젝트를 생성합니다."""

    try:
        proc = _run_cmd(
            ["npx", "--yes", "create-vite", "frontend", "--template", "react-ts"],
            cwd=packages_dir,
            timeout=180,
        )
    except subprocess.TimeoutExpired:
        proc = None

    if proc and proc.returncode == 0 and os.path.exists(os.path.join(fe_dir, "src", "main.tsx")):
        # 추가 의존성 설치
        _run_cmd(
            ["npm", "install",
             "react-router-dom", "axios"],
            cwd=fe_dir,
        )

        # 불필요한 보일러플레이트 정리
        _cleanup_vite_boilerplate(fe_dir)

        # package.json name 수정
        _patch_package_name(fe_dir, "@brawl-and-build/frontend")

        # vite.config에 프록시 설정 추가
        _patch_vite_config(fe_dir)
    else:
        # create-vite 실패 시 fallback
        _scaffold_frontend_fallback(fe_dir)


def _scaffold_shared(shared_dir: str):
    """shared 패키지는 CLI가 없으므로 수동 생성합니다."""
    os.makedirs(os.path.join(shared_dir, "src", "types"), exist_ok=True)

    _write_json(shared_dir, "package.json", {
        "name": "@brawl-and-build/shared",
        "version": "0.1.0",
        "main": "src/index.ts",
        "types": "src/index.ts",
        "devDependencies": {
            "typescript": "^5.0.0",
        },
    })

    _write_json(shared_dir, "tsconfig.json", {
        "compilerOptions": {
            "target": "ES2020",
            "module": "ESNext",
            "moduleResolution": "bundler",
            "declaration": True,
            "strict": True,
            "skipLibCheck": True,
            "outDir": "./dist",
        },
        "include": ["src/**/*"],
    })

    # 기본 index.ts
    index_path = os.path.join(shared_dir, "src", "index.ts")
    if not os.path.exists(index_path):
        with open(index_path, "w") as f:
            f.write("// 공유 타입 엔트리포인트 - Build 시 자동 생성됩니다\n")


# ══════════════════════════════════════════
#  보일러플레이트 정리
# ══════════════════════════════════════════

def _cleanup_nest_boilerplate(be_dir: str):
    """nest new가 만든 불필요한 파일을 정리합니다."""
    remove_files = [
        "src/app.controller.spec.ts",  # 기본 테스트
        "src/app.controller.ts",       # Hello World 컨트롤러
        "src/app.service.ts",          # Hello World 서비스
        "README.md",                    # nest 기본 README
    ]
    for f in remove_files:
        filepath = os.path.join(be_dir, f)
        if os.path.exists(filepath):
            os.remove(filepath)

    # app.module.ts를 깔끔하게 교체 (AppController/Service import 제거)
    app_module_path = os.path.join(be_dir, "src", "app.module.ts")
    _write_file_direct(app_module_path, """import { Module } from '@nestjs/common';
import { ConfigModule } from '@nestjs/config';

@Module({
  imports: [
    ConfigModule.forRoot({ isGlobal: true }),
    // 여기에 기능 모듈을 추가하세요 (Build 시 자동 패치됩니다)
  ],
  controllers: [],
  providers: [],
})
export class AppModule {}
""")


def _cleanup_vite_boilerplate(fe_dir: str):
    """create-vite가 만든 불필요한 파일을 정리합니다."""
    remove_files = [
        "src/App.css",
        "src/index.css",
        "public/vite.svg",
        "src/assets/react.svg",
    ]
    for f in remove_files:
        filepath = os.path.join(fe_dir, f)
        if os.path.exists(filepath):
            os.remove(filepath)

    # assets 폴더가 비었으면 삭제
    assets_dir = os.path.join(fe_dir, "src", "assets")
    if os.path.exists(assets_dir) and not os.listdir(assets_dir):
        os.rmdir(assets_dir)

    # App.tsx를 깔끔한 라우터 템플릿으로 교체
    app_tsx_path = os.path.join(fe_dir, "src", "App.tsx")
    _write_file_direct(app_tsx_path, """import { BrowserRouter, Routes, Route } from 'react-router-dom';

function App() {
  return (
    <BrowserRouter>
      <Routes>
        <Route path="/" element={<div>Home</div>} />
        {/* 여기에 기능 라우트를 추가하세요 (Build 시 안내됩니다) */}
      </Routes>
    </BrowserRouter>
  );
}

export default App;
""")

    # main.tsx 정리 (CSS import 제거)
    main_tsx_path = os.path.join(fe_dir, "src", "main.tsx")
    _write_file_direct(main_tsx_path, """import { StrictMode } from 'react';
import { createRoot } from 'react-dom/client';
import App from './App';

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <App />
  </StrictMode>,
);
""")


# ══════════════════════════════════════════
#  패치 헬퍼
# ══════════════════════════════════════════

def _patch_package_name(pkg_dir: str, name: str):
    """package.json의 name을 수정합니다."""
    pkg_path = os.path.join(pkg_dir, "package.json")
    if os.path.exists(pkg_path):
        with open(pkg_path, "r") as f:
            data = json.load(f)
        data["name"] = name
        with open(pkg_path, "w") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)


def _patch_vite_config(fe_dir: str):
    """vite.config.ts에 프록시 설정을 추가합니다."""
    config_path = os.path.join(fe_dir, "vite.config.ts")
    _write_file_direct(config_path, """import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';

export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: {
      '/api': {
        target: 'http://localhost:3000',
        changeOrigin: true,
        rewrite: (path) => path.replace(/^\\/api/, ''),
      },
    },
  },
});
""")


def _patch_app_module(output_dir: str, feature_name: str):
    """app.module.ts에 기능 모듈을 자동 import합니다."""
    if not feature_name:
        return

    app_module_path = os.path.join(output_dir, "packages", "backend", "src", "app.module.ts")
    if not os.path.exists(app_module_path):
        return

    with open(app_module_path, "r", encoding="utf-8") as f:
        content = f.read()

    # feature_name → PascalCase module name 추정
    # "사용자 로그인" → "auth", "user-login" → "UserLogin"
    # LLM이 생성한 모듈 디렉토리를 찾아서 자동 패치
    src_dir = os.path.join(output_dir, "packages", "backend", "src")
    feature_dirs = [
        d for d in os.listdir(src_dir)
        if os.path.isdir(os.path.join(src_dir, d))
        and d not in ("common", "config", "shared")
        and os.path.exists(os.path.join(src_dir, d, f"{d}.module.ts"))
    ]

    for feature_dir in feature_dirs:
        module_class = _to_pascal_case(feature_dir) + "Module"
        import_line = f"import {{ {module_class} }} from './{feature_dir}/{feature_dir}.module';"

        # 이미 import 되어 있으면 skip
        if module_class in content:
            continue

        # import 추가
        content = import_line + "\n" + content

        # imports 배열에 추가
        if "imports: [" in content:
            content = content.replace(
                "imports: [",
                f"imports: [\n    {module_class},",
            )

    with open(app_module_path, "w", encoding="utf-8") as f:
        f.write(content)


def _to_pascal_case(name: str) -> str:
    """kebab-case → PascalCase 변환."""
    return "".join(word.capitalize() for word in name.split("-"))


# ══════════════════════════════════════════
#  Fallback (CLI 실패 시)
# ══════════════════════════════════════════

def _scaffold_backend_fallback(be_dir: str):
    """nest CLI가 없을 때 수동으로 backend를 생성합니다."""
    os.makedirs(os.path.join(be_dir, "src"), exist_ok=True)

    _write_json(be_dir, "package.json", {
        "name": "@brawl-and-build/backend",
        "version": "0.1.0",
        "scripts": {
            "build": "nest build",
            "start": "nest start",
            "start:dev": "nest start --watch",
            "start:prod": "node dist/main",
        },
        "dependencies": {
            "@nestjs/common": "^10.0.0",
            "@nestjs/core": "^10.0.0",
            "@nestjs/platform-express": "^10.0.0",
            "@nestjs/config": "^3.0.0",
            "@nestjs/jwt": "^10.0.0",
            "@nestjs/passport": "^10.0.0",
            "@nestjs/typeorm": "^10.0.0",
            "@nestjs/throttler": "^5.0.0",
            "typeorm": "^0.3.0",
            "pg": "^8.11.0",
            "bcrypt": "^5.1.0",
            "passport": "^0.7.0",
            "passport-jwt": "^4.0.0",
            "class-validator": "^0.14.0",
            "class-transformer": "^0.5.0",
            "reflect-metadata": "^0.2.0",
            "rxjs": "^7.8.0",
        },
        "devDependencies": {
            "@nestjs/cli": "^10.0.0",
            "@nestjs/schematics": "^10.0.0",
            "@types/bcrypt": "^5.0.0",
            "@types/passport-jwt": "^4.0.0",
            "@types/node": "^20.0.0",
            "typescript": "^5.0.0",
            "ts-node": "^10.9.0",
        },
    })

    _write_json(be_dir, "tsconfig.json", {
        "compilerOptions": {
            "module": "commonjs",
            "declaration": True,
            "removeComments": True,
            "emitDecoratorMetadata": True,
            "experimentalDecorators": True,
            "allowSyntheticDefaultImports": True,
            "target": "ES2021",
            "sourceMap": True,
            "outDir": "./dist",
            "baseUrl": "./",
            "incremental": True,
            "strict": True,
            "skipLibCheck": True,
            "forceConsistentCasingInFileNames": True,
        },
        "include": ["src/**/*"],
    })

    _write_json(be_dir, "nest-cli.json", {
        "$schema": "https://json.schemastore.org/nest-cli",
        "collection": "@nestjs/schematics",
        "sourceRoot": "src",
    })

    # main.ts
    _write_file_direct(os.path.join(be_dir, "src", "main.ts"), """import { NestFactory } from '@nestjs/core';
import { ValidationPipe } from '@nestjs/common';
import { AppModule } from './app.module';

async function bootstrap() {
  const app = await NestFactory.create(AppModule);
  app.useGlobalPipes(new ValidationPipe({ whitelist: true, transform: true }));
  app.enableCors();
  await app.listen(3000);
  console.log('Server running on http://localhost:3000');
}
bootstrap();
""")

    # app.module.ts
    _write_file_direct(os.path.join(be_dir, "src", "app.module.ts"), """import { Module } from '@nestjs/common';
import { ConfigModule } from '@nestjs/config';

@Module({
  imports: [
    ConfigModule.forRoot({ isGlobal: true }),
  ],
  controllers: [],
  providers: [],
})
export class AppModule {}
""")


def _scaffold_frontend_fallback(fe_dir: str):
    """create-vite가 없을 때 수동으로 frontend를 생성합니다."""
    os.makedirs(os.path.join(fe_dir, "src"), exist_ok=True)

    _write_json(fe_dir, "package.json", {
        "name": "@brawl-and-build/frontend",
        "version": "0.1.0",
        "type": "module",
        "scripts": {
            "dev": "vite",
            "build": "tsc && vite build",
            "preview": "vite preview",
        },
        "dependencies": {
            "react": "^18.0.0",
            "react-dom": "^18.0.0",
            "react-router-dom": "^6.20.0",
            "axios": "^1.6.0",
        },
        "devDependencies": {
            "@types/react": "^18.0.0",
            "@types/react-dom": "^18.0.0",
            "@vitejs/plugin-react": "^4.2.0",
            "typescript": "^5.0.0",
            "vite": "^5.0.0",
        },
    })

    _write_json(fe_dir, "tsconfig.json", {
        "compilerOptions": {
            "target": "ES2020",
            "useDefineForClassFields": True,
            "lib": ["ES2020", "DOM", "DOM.Iterable"],
            "module": "ESNext",
            "skipLibCheck": True,
            "moduleResolution": "bundler",
            "allowImportingTsExtensions": True,
            "resolveJsonModule": True,
            "isolatedModules": True,
            "noEmit": True,
            "jsx": "react-jsx",
            "strict": True,
            "forceConsistentCasingInFileNames": True,
        },
        "include": ["src"],
    })

    _patch_vite_config(fe_dir)

    # index.html
    _write_file_direct(os.path.join(fe_dir, "index.html"), """<!doctype html>
<html lang="ko">
  <head>
    <meta charset="UTF-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1.0" />
    <title>Brawl & Build App</title>
  </head>
  <body>
    <div id="root"></div>
    <script type="module" src="/src/main.tsx"></script>
  </body>
</html>
""")

    # main.tsx
    _write_file_direct(os.path.join(fe_dir, "src", "main.tsx"), """import { StrictMode } from 'react';
import { createRoot } from 'react-dom/client';
import App from './App';

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <App />
  </StrictMode>,
);
""")

    # App.tsx
    _write_file_direct(os.path.join(fe_dir, "src", "App.tsx"), """import { BrowserRouter, Routes, Route } from 'react-router-dom';

function App() {
  return (
    <BrowserRouter>
      <Routes>
        <Route path="/" element={<div>Home</div>} />
      </Routes>
    </BrowserRouter>
  );
}

export default App;
""")


# ══════════════════════════════════════════
#  유틸리티
# ══════════════════════════════════════════

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


def _write_json(directory: str, filename: str, data: dict):
    """JSON 파일을 작성합니다."""
    filepath = os.path.join(directory, filename)
    os.makedirs(os.path.dirname(filepath), exist_ok=True)
    with open(filepath, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)


def _write_file(directory: str, filename: str, content: str):
    """디렉토리 + 파일명으로 텍스트 파일을 작성합니다."""
    filepath = os.path.join(directory, filename)
    os.makedirs(os.path.dirname(filepath), exist_ok=True)
    with open(filepath, "w", encoding="utf-8") as f:
        f.write(content)


def _write_file_direct(filepath: str, content: str):
    """절대경로로 텍스트 파일을 작성합니다."""
    os.makedirs(os.path.dirname(filepath), exist_ok=True)
    with open(filepath, "w", encoding="utf-8") as f:
        f.write(content)


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
