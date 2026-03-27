#!/usr/bin/env python3
"""Brawl & Build 로컬 검증 스크립트.

MCP 서버를 거치지 않고 각 모듈을 직접 호출하여 테스트합니다.
전체 실행 또는 개별 단계만 선택 가능합니다.

Usage:
    python test_local.py                  # 전체 진단 (환경 + GitHub + MCP 로드)
    python test_local.py --step env       # 환경만 검사
    python test_local.py --step github    # GitHub 연결만 검사
    python test_local.py --step mcp       # MCP 서버 로드만 검사
    python test_local.py --step discuss   # 토론만 실행 (API 비용 발생)
    python test_local.py --step build     # 코드 생성만 실행 (API 비용 발생)
    python test_local.py --step pr        # PR 생성만 실행
    python test_local.py --full --target ~/path/to/repo  # 전체 실행
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
    packages = {
        "langchain": "langchain",
        "langchain_anthropic": "langchain-anthropic",
        "langgraph": "langgraph",
        "mcp": "mcp[cli]",
        "requests": "requests",
        "dotenv": "python-dotenv",
        "pydantic": "pydantic",
    }
    for module, pip_name in packages.items():
        try:
            __import__(module)
            ok(f"{module} 설치됨")
        except ImportError:
            fail(f"{module} 미설치 → pip install {pip_name}")
            errors.append(module)

    # 환경 변수
    anthropic_key = os.environ.get("ANTHROPIC_API_KEY", "")
    github_token = os.environ.get("GITHUB_TOKEN", "")

    if anthropic_key and anthropic_key.startswith("sk-ant-"):
        ok(f"ANTHROPIC_API_KEY 설정됨 ({anthropic_key[:12]}...)")
    else:
        fail("ANTHROPIC_API_KEY 미설정 또는 잘못된 형식")
        errors.append("ANTHROPIC_API_KEY")

    if github_token and (github_token.startswith("ghp_") or github_token.startswith("github_pat_")):
        ok(f"GITHUB_TOKEN 설정됨 ({github_token[:8]}...)")
    else:
        fail("GITHUB_TOKEN 미설정 또는 잘못된 형식 (ghp_ 또는 github_pat_ 으로 시작해야 함)")
        errors.append("GITHUB_TOKEN")

    # CLI 도구
    for tool in ["git", "node", "npx"]:
        proc = subprocess.run(["which", tool], capture_output=True, text=True)
        if proc.returncode == 0:
            # 버전도 확인
            ver = subprocess.run([tool, "--version"], capture_output=True, text=True)
            ok(f"{tool} → {proc.stdout.strip()} ({ver.stdout.strip()[:30]})")
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
    try:
        resp = requests.get(
            "https://api.github.com/user",
            headers={"Authorization": f"token {token}"},
            timeout=10,
        )
    except requests.ConnectionError:
        fail("GitHub API 연결 실패 (네트워크 확인)")
        return False

    if resp.status_code == 200:
        user = resp.json()
        ok(f"GitHub 인증 성공: {user['login']} ({user.get('name', '')})")
    else:
        fail(f"GitHub 인증 실패: HTTP {resp.status_code}")
        errors.append("auth")
        return False

    # 토큰 권한 (scopes)
    scopes = resp.headers.get("X-OAuth-Scopes", "")
    if "repo" in scopes:
        ok(f"토큰 권한: {scopes}")
    else:
        warn(f"토큰 권한에 'repo' 없음: {scopes}")
        warn("  → PR 생성에 'repo' 권한이 필요합니다")
        warn("  → https://github.com/settings/tokens 에서 권한 추가")
        errors.append("scope")

    # target repo 확인
    if target_path:
        proc = subprocess.run(
            ["git", "remote", "get-url", "origin"],
            cwd=target_path, capture_output=True, text=True,
        )
        url = proc.stdout.strip()
        if not url:
            fail(f"target_path에 git remote가 없습니다: {target_path}")
            errors.append("no_remote")
        else:
            match = re.search(r'github\.com[:/]([^/]+)/([^/.]+)', url)
            if match:
                owner, repo = match.group(1), match.group(2)
                ok(f"Target repo: {owner}/{repo}")

                resp = requests.get(
                    f"https://api.github.com/repos/{owner}/{repo}",
                    headers={"Authorization": f"token {token}"},
                    timeout=10,
                )
                if resp.status_code == 200:
                    repo_info = resp.json()
                    ok(f"Repo 접근 OK (private={repo_info.get('private')}, default_branch={repo_info.get('default_branch')})")
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
    warn("이 단계는 Anthropic API를 호출합니다 (비용 발생)")

    from core.graph import run_discussion
    from core.exporter import state_to_result, export_markdown, export_json
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
                max_rounds=1,
                enable_build=False,
            )

        elapsed = time.time() - start
        result = state_to_result(final_state)

        ok(f"토론 완료 ({elapsed:.1f}s)")
        info(f"결정사항: {len(result.decisions)}건")
        for d in result.decisions[:3]:
            info(f"  - {d[:80]}...")
        info(f"미해결: {len(result.unresolved)}건")
        info(f"비용: {tracker.to_dict()}")

        out_dir = os.path.join(target_path, "docs", "discussions") if target_path else "output"
        md_path = export_markdown(result, output_dir=out_dir)
        json_path = export_json(result, output_dir=out_dir)
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
    warn("이 단계는 Anthropic API를 호출합니다 (비용 발생)")

    from core.graph import run_discussion
    from core.exporter import state_to_result
    from core.code_generator import save_generated_code
    from core.cost_tracker import track_cost

    project = "테스트 프로젝트"
    feature = "사용자 로그인"
    previous_context = ""

    if target_path:
        from core.project_config import load_config, build_previous_context, mark_feature_done
        config = load_config(target_path)
        if config:
            project = config.project
            previous_context = build_previous_context(target_path)

    info(f"토론 + 코드 생성: '{feature}' (1라운드, build=True)")
    start = time.time()

    try:
        with track_cost() as tracker:
            final_state = run_discussion(
                project_description=project,
                feature_name=feature,
                feature_description="이메일/비밀번호 기반 로그인",
                max_rounds=1,
                enable_build=True,
                previous_context=previous_context,
            )

        elapsed = time.time() - start
        ok(f"토론 + 코드 생성 완료 ({elapsed:.1f}s)")

        code_dir = target_path if target_path else "generated"
        saved_files = save_generated_code(final_state, output_dir=code_dir)
        ok(f"저장된 파일 {len(saved_files)}개:")
        for f in saved_files:
            info(f"  {f}")

        if target_path:
            mark_feature_done(target_path, feature)
            ok(f".brawl.json에 '{feature}' 완료 기록")

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
            warn("변경사항이 없습니다 — 커밋할 내용 없음")
            info("build_code를 먼저 실행하세요: python test_local.py --step build --target <path>")
            return True

        info(f"변경 파일 {len(changes.splitlines())}개")

        # 현재 브랜치 저장
        cur_branch = subprocess.run(
            ["git", "branch", "--show-current"],
            cwd=target_path, capture_output=True, text=True,
        ).stdout.strip()

        # 기존 브랜치 삭제 (있으면)
        subprocess.run(
            ["git", "branch", "-D", branch_name],
            cwd=target_path, capture_output=True, text=True,
        )

        # 브랜치 생성 + 커밋
        cmds = [
            (["git", "checkout", "-b", branch_name], "브랜치 생성"),
            (["git", "add", "."], "스테이징"),
            (["git", "commit", "-m", f"feat: {feature} scaffold by brawl-and-build"], "커밋"),
        ]
        for cmd, label in cmds:
            proc = subprocess.run(cmd, cwd=target_path, capture_output=True, text=True)
            if proc.returncode != 0 and "nothing to commit" not in proc.stdout:
                fail(f"{label} 실패: {proc.stderr.strip()}")
                return False
            ok(label)

        # push
        push_url = f"https://x-access-token:{token}@github.com/{owner}/{repo}.git"
        proc = subprocess.run(
            ["git", "push", "-u", push_url, branch_name, "--force"],
            cwd=target_path, capture_output=True, text=True, timeout=60,
        )
        if proc.returncode != 0:
            fail(f"push 실패: {proc.stderr.replace(token, '***')}")
            return False
        ok("git push 성공")

        # PR 생성 (GitHub REST API)
        headers_dict = {
            "Authorization": f"token {token}",
            "Accept": "application/vnd.github.v3+json",
        }
        pr_data = {
            "title": f"feat: {feature}",
            "body": (
                f"## feat: {feature}\n\n"
                f"Brawl & Build 로컬 테스트에서 생성된 PR입니다.\n\n"
                f"---\n*Generated by 🥊 Brawl & Build*"
            ),
            "head": branch_name,
            "base": "main",
        }
        resp = requests.post(
            f"https://api.github.com/repos/{owner}/{repo}/pulls",
            json=pr_data, headers=headers_dict, timeout=30,
        )
        if resp.status_code == 201:
            pr_url = resp.json()["html_url"]
            ok(f"PR 생성 성공: {pr_url}")
        elif resp.status_code == 422:
            error_msg = resp.json().get("errors", [{}])[0].get("message", "")
            if "already exists" in error_msg.lower():
                warn("PR이 이미 존재합니다 (push는 완료)")
            else:
                fail(f"PR 생성 실패 (422): {resp.json()}")
                return False
        else:
            fail(f"PR 생성 실패: HTTP {resp.status_code} — {resp.text[:200]}")
            return False

        return True

    except Exception as e:
        fail(f"PR 테스트 실패: {e}")
        import traceback
        traceback.print_exc()
        return False

    finally:
        # 원래 브랜치로 복귀
        subprocess.run(
            ["git", "checkout", cur_branch],
            cwd=target_path, capture_output=True, text=True,
        )


# ═══════════════════════════════════════
#  Bonus: MCP 서버 로드 테스트
# ═══════════════════════════════════════

def test_mcp_load():
    header("Bonus: MCP 서버 로드 검사")

    try:
        import importlib.util
        spec = importlib.util.spec_from_file_location("mcp_server", ROOT / "mcp_server.py")
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)

        # 등록된 도구 확인 (FastMCP 내부 구조)
        tools = []
        for attr in ["_tool_manager", "_tools"]:
            mgr = getattr(mod.mcp, attr, None)
            if mgr:
                if hasattr(mgr, "_tools"):
                    tools = list(mgr._tools.keys())
                elif isinstance(mgr, dict):
                    tools = list(mgr.keys())
                break

        if tools:
            ok(f"MCP 도구 {len(tools)}개 등록됨:")
            for t in tools:
                info(f"  - {t}")
        else:
            info("MCP 도구 목록 직접 확인 불가 (FastMCP 내부 구조 변경)")
            info("서버 로드 자체는 성공")

        ok("mcp_server.py 로드 성공 (문법 + 의존성 OK)")
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
    parser = argparse.ArgumentParser(
        description="🥊 Brawl & Build 로컬 테스트",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
예시:
  python test_local.py                                    # 환경 + GitHub + MCP 검사
  python test_local.py --step discuss                     # 토론만 테스트
  python test_local.py --step pr --target ~/repo          # PR 생성만 테스트
  python test_local.py --full --target ~/repo             # 전체 플로우 실행
        """,
    )
    parser.add_argument(
        "--step",
        choices=["env", "github", "discuss", "build", "pr", "mcp", "all"],
        default="all",
        help="실행할 테스트 단계 (기본: all = env + github + mcp)",
    )
    parser.add_argument(
        "--target",
        default=None,
        help="대상 프로젝트 경로 (예: ~/Documents/since/brawl-test-repo)",
    )
    parser.add_argument(
        "--full",
        action="store_true",
        help="discuss + build + pr 포함 전체 실행 (API 비용 발생!)",
    )
    args = parser.parse_args()

    target = os.path.expanduser(args.target) if args.target else None

    print(f"\n{BOLD}🥊 Brawl & Build — 로컬 테스트{RESET}")
    print(f"   엔진: {ROOT}")
    if target:
        print(f"   타겟: {target}")
    print()

    results = {}

    # 기본 검사 (all)
    if args.step in ("env", "all"):
        results["env"] = check_env()

    if args.step in ("github", "all"):
        results["github"] = check_github(target)

    if args.step in ("mcp", "all"):
        results["mcp"] = test_mcp_load()

    # API 호출 테스트 (개별 또는 --full)
    if args.step == "discuss" or args.full:
        results["discuss"] = test_discuss(target)

    if args.step == "build" or args.full:
        results["build"] = test_build(target)

    if args.step == "pr" or args.full:
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
        print(f"  개별 실행: python test_local.py --step <step_name>")
        sys.exit(1)
    else:
        print(f"\n  {GREEN}모든 테스트 통과! Claude Desktop 시연 준비 완료.{RESET}")


if __name__ == "__main__":
    main()
