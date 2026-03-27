"""Brawl & Build MCP Server.

Claude Desktop에서 대화로 토론을 시작하고,
코드 생성, PR 생성까지 할 수 있는 MCP 서버.

사용 예시 (Claude Desktop에서):
  "소셜 커머스 플랫폼에서 회원가입 기능을 토론해줘"
  "이전 토론 결과 보여줘"
  "회원가입 기능 코드 생성해줘"
"""

import sys
import os
import json
import re
import subprocess
import threading
import uuid
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from dotenv import load_dotenv

load_dotenv()

from mcp.server.fastmcp import FastMCP
from core.graph import run_discussion
from core.exporter import state_to_result, export_markdown, export_json
from core.cost_tracker import track_cost
from core.project_config import (
    load_config, save_config, init_config,
    mark_feature_done, build_previous_context,
)
from core.code_generator import save_generated_code, scaffold_project

mcp = FastMCP(name="brawl-and-build")


# ══════════════════════════════════════════
#  비동기 작업 관리
# ══════════════════════════════════════════

_tasks: dict[str, dict] = {}


def _create_task(task_type: str, feature_name: str) -> str:
    """새 작업을 생성하고 task_id를 반환합니다."""
    task_id = str(uuid.uuid4())[:8]
    _tasks[task_id] = {
        "task_id": task_id,
        "type": task_type,
        "feature": feature_name,
        "status": "running",
        "started_at": datetime.now().isoformat(),
        "finished_at": None,
        "result": None,
        "error": None,
    }
    return task_id


def _finish_task(task_id: str, result: dict):
    """작업을 완료 상태로 업데이트합니다."""
    if task_id in _tasks:
        _tasks[task_id]["status"] = "completed"
        _tasks[task_id]["finished_at"] = datetime.now().isoformat()
        _tasks[task_id]["result"] = result


def _fail_task(task_id: str, error: str):
    """작업을 실패 상태로 업데이트합니다."""
    if task_id in _tasks:
        _tasks[task_id]["status"] = "error"
        _tasks[task_id]["finished_at"] = datetime.now().isoformat()
        _tasks[task_id]["error"] = error


# ══════════════════════════════════════════
#  Tool 1: 프로젝트 초기화
# ══════════════════════════════════════════

@mcp.tool()
def init_project(target_path: str, project_name: str) -> str:
    """대상 프로젝트에 .brawl.json 설정 파일을 초기화합니다.

    Args:
        target_path: 대상 프로젝트 절대 경로
        project_name: 프로젝트 이름 (예: "소셜 커머스 플랫폼")
    """
    target = os.path.abspath(target_path)
    config = init_config(target, project_name)

    # 프로젝트 scaffold (nest new, create-vite) - 최초 1회만
    scaffold_result = scaffold_project(target)

    return json.dumps({
        "status": "ok",
        "message": f"프로젝트 '{project_name}' 초기화 완료",
        "config_path": os.path.join(target, ".brawl.json"),
        "scaffold": "created" if not scaffold_result.get("skipped") else "already_exists",
        "config": {
            "project": config.project,
            "stack": config.stack,
            "roles": config.roles,
            "rounds": config.rounds,
        },
    }, ensure_ascii=False, indent=2)


# ══════════════════════════════════════════
#  Tool 2: 토론 실행 (Brawl) - async
# ══════════════════════════════════════════

@mcp.tool()
def discuss(
    feature_name: str,
    project_name: str = "",
    feature_description: str = "",
    target_path: str = "",
    rounds: int = 2,
) -> str:
    """PM, BE, FE, Designer 역할의 AI 에이전트들이 기능에 대해 토론합니다.

    비동기로 실행됩니다. 반환된 task_id로 get_task_status를 호출하여 결과를 확인하세요.

    Args:
        feature_name: 토론할 기능 이름 (예: "회원가입")
        project_name: 프로젝트 이름 (.brawl.json 있으면 생략 가능)
        feature_description: 기능 추가 설명
        target_path: 대상 프로젝트 경로 (이전 토론 컨텍스트 로드용)
        rounds: 토론 라운드 수 (기본: 2)
    """
    # 설정 파일에서 로드
    previous_context = ""
    if target_path:
        target = os.path.abspath(target_path)
        config = load_config(target)
        if config:
            project_name = project_name or config.project
            rounds = rounds or config.rounds
            previous_context = build_previous_context(target)

    if not project_name:
        return json.dumps({"error": "project_name 또는 target_path(.brawl.json) 필요"})

    task_id = _create_task("discuss", feature_name)

    def _run():
        try:
            with track_cost() as tracker:
                final_state = run_discussion(
                    project_description=project_name,
                    feature_name=feature_name,
                    feature_description=feature_description,
                    max_rounds=rounds,
                    enable_build=False,
                    previous_context=previous_context,
                )

            result = state_to_result(final_state)

            # 파일 저장
            output_dir = "output"
            if target_path:
                output_dir = os.path.join(os.path.abspath(target_path), "docs", "discussions")

            md_path = export_markdown(result, output_dir=output_dir)
            json_path = export_json(result, output_dir=output_dir)

            _finish_task(task_id, {
                "feature": feature_name,
                "decisions": result.decisions,
                "unresolved": result.unresolved,
                "summary": result.summary,
                "total_rounds": result.total_rounds,
                "files": {"markdown": md_path, "json": json_path},
                "cost": tracker.to_dict(),
            })
        except Exception as e:
            _fail_task(task_id, str(e))

    thread = threading.Thread(target=_run, daemon=True)
    thread.start()

    return json.dumps({
        "status": "started",
        "task_id": task_id,
        "message": f"'{feature_name}' 토론이 시작되었습니다. get_task_status('{task_id}')로 진행 상황을 확인하세요.",
    }, ensure_ascii=False, indent=2)


# ══════════════════════════════════════════
#  Tool 3: 코드 생성 (Build) - async
# ══════════════════════════════════════════

@mcp.tool()
def build_code(
    feature_name: str,
    project_name: str = "",
    feature_description: str = "",
    target_path: str = "",
    rounds: int = 2,
) -> str:
    """토론 후 코드를 생성합니다 (Brawl + Build).

    NestJS 백엔드, React TS 프론트엔드, 공유 타입, API 명세를 생성합니다.
    비동기로 실행됩니다. 반환된 task_id로 get_task_status를 호출하여 결과를 확인하세요.

    Args:
        feature_name: 기능 이름 (예: "회원가입")
        project_name: 프로젝트 이름
        feature_description: 기능 추가 설명
        target_path: 대상 프로젝트 경로 (코드가 여기에 생성됨)
        rounds: 토론 라운드 수
    """
    previous_context = ""
    if target_path:
        target = os.path.abspath(target_path)
        config = load_config(target)
        if config:
            project_name = project_name or config.project
            previous_context = build_previous_context(target)

    if not project_name:
        return json.dumps({"error": "project_name 또는 target_path(.brawl.json) 필요"})

    task_id = _create_task("build_code", feature_name)

    def _run():
        try:
            with track_cost() as tracker:
                final_state = run_discussion(
                    project_description=project_name,
                    feature_name=feature_name,
                    feature_description=feature_description,
                    max_rounds=rounds,
                    enable_build=True,
                    previous_context=previous_context,
                )

            result = state_to_result(final_state)

            # 코드 저장
            code_dir = os.path.abspath(target_path) if target_path else "generated"
            saved_files = save_generated_code(final_state, output_dir=code_dir)

            # 토론 기록 저장
            docs_dir = os.path.join(code_dir, "docs", "discussions") if target_path else "output"
            md_path = export_markdown(result, output_dir=docs_dir)
            json_path = export_json(result, output_dir=docs_dir)

            # .brawl.json 업데이트
            if target_path:
                mark_feature_done(os.path.abspath(target_path), feature_name)

            _finish_task(task_id, {
                "feature": feature_name,
                "decisions": result.decisions,
                "unresolved": result.unresolved,
                "summary": result.summary,
                "generated_files": saved_files,
                "discussion_files": {"markdown": md_path, "json": json_path},
                "cost": tracker.to_dict(),
            })
        except Exception as e:
            _fail_task(task_id, str(e))

    thread = threading.Thread(target=_run, daemon=True)
    thread.start()

    return json.dumps({
        "status": "started",
        "task_id": task_id,
        "message": f"'{feature_name}' 토론 + 코드 생성이 시작되었습니다. get_task_status('{task_id}')로 진행 상황을 확인하세요.",
    }, ensure_ascii=False, indent=2)


# ══════════════════════════════════════════
#  Tool 4: 작업 상태 조회 (NEW)
# ══════════════════════════════════════════

@mcp.tool()
def get_task_status(task_id: str) -> str:
    """비동기 작업(discuss, build_code)의 진행 상태를 확인합니다.

    Args:
        task_id: discuss 또는 build_code 호출 시 반환된 task_id
    """
    task = _tasks.get(task_id)

    if not task:
        return json.dumps({
            "status": "not_found",
            "message": f"task_id '{task_id}'를 찾을 수 없습니다.",
            "available_tasks": [
                {"task_id": t["task_id"], "type": t["type"], "feature": t["feature"], "status": t["status"]}
                for t in _tasks.values()
            ],
        }, ensure_ascii=False, indent=2)

    response = {
        "task_id": task["task_id"],
        "type": task["type"],
        "feature": task["feature"],
        "status": task["status"],
        "started_at": task["started_at"],
    }

    if task["status"] == "running":
        response["message"] = "아직 진행 중입니다. 잠시 후 다시 확인해주세요."
    elif task["status"] == "completed":
        response["finished_at"] = task["finished_at"]
        response["result"] = task["result"]
    elif task["status"] == "error":
        response["finished_at"] = task["finished_at"]
        response["error"] = task["error"]

    return json.dumps(response, ensure_ascii=False, indent=2)


# ══════════════════════════════════════════
#  Tool 5: PR 생성
# ══════════════════════════════════════════

@mcp.tool()
def create_pr(
    feature_name: str,
    target_path: str,
    base_branch: str = "main",
) -> str:
    """대상 프로젝트에서 feature 브랜치를 만들고 PR을 생성합니다.

    Args:
        feature_name: 기능 이름 (브랜치명에 사용)
        target_path: 대상 프로젝트 경로
        base_branch: 베이스 브랜치 (기본: main)
    """
    import requests as http_requests
    from hashlib import md5

    target = os.path.abspath(target_path)

    # GitHub 토큰 확인
    github_token = os.environ.get("GITHUB_TOKEN")
    if not github_token:
        return json.dumps({
            "status": "error",
            "error": "GITHUB_TOKEN이 설정되지 않았습니다. .env 또는 MCP env에 추가하세요.",
        }, ensure_ascii=False, indent=2)

    # 토론 결과에서 PR description 로드
    pr_body = _load_pr_description(target, feature_name)

    # 브랜치명 생성 (비ASCII/특수문자 제거, 공백→하이픈)
    slug = re.sub(r'[^a-zA-Z0-9\s-]', '', feature_name)
    slug = re.sub(r'[\s]+', '-', slug).strip('-').lower()
    if not slug:
        slug = md5(feature_name.encode()).hexdigest()[:8]
    branch_name = f"feature/{slug}"

    try:
        env = os.environ.copy()
        extra_paths = [
            "/opt/homebrew/bin",
            "/usr/local/bin",
            os.path.expanduser("~/.nvm/versions/node/v20.12.2/bin"),
        ]
        env["PATH"] = ":".join(extra_paths) + ":" + env.get("PATH", "")

        # git remote에서 owner/repo 추출
        owner, repo = _get_github_repo_info(target, env)
        if not owner:
            return json.dumps({
                "status": "error",
                "error": "GitHub remote URL을 파싱할 수 없습니다. git remote -v 를 확인하세요.",
            }, ensure_ascii=False, indent=2)

        # 이미 해당 브랜치가 있으면 삭제 후 재생성
        _run_cmd(["git", "branch", "-D", branch_name], cwd=target, env=env, ignore_error=True)

        # ── Step 1: git branch + add + commit + push ──
        git_cmds = [
            ["git", "checkout", "-b", branch_name],
            ["git", "add", "."],
            ["git", "commit", "-m", f"feat: {feature_name} scaffold by brawl-and-build"],
        ]

        results = []
        for cmd in git_cmds:
            try:
                proc = subprocess.run(
                    cmd, cwd=target, env=env,
                    capture_output=True, text=True, timeout=60,
                )
            except FileNotFoundError as fnf:
                return json.dumps({
                    "status": "error",
                    "step": " ".join(cmd),
                    "error": f"명령어를 찾을 수 없습니다: {fnf}",
                    "completed_steps": results,
                }, ensure_ascii=False, indent=2)

            results.append({
                "cmd": " ".join(cmd),
                "returncode": proc.returncode,
                "stdout": proc.stdout.strip(),
                "stderr": proc.stderr.strip(),
            })

            if proc.returncode != 0:
                if "nothing to commit" in proc.stdout:
                    results[-1]["skipped"] = True
                    continue
                return json.dumps({
                    "status": "error",
                    "step": " ".join(cmd),
                    "error": proc.stderr.strip() or proc.stdout.strip(),
                    "completed_steps": results,
                }, ensure_ascii=False, indent=2)

        # ── Step 2: push (토큰을 URL에 포함하여 인증) ──
        push_url = f"https://x-access-token:{github_token}@github.com/{owner}/{repo}.git"
        push_cmd = ["git", "push", "-u", push_url, branch_name, "--force"]
        try:
            proc = subprocess.run(
                push_cmd, cwd=target, env=env,
                capture_output=True, text=True, timeout=60,
            )
        except FileNotFoundError as fnf:
            return json.dumps({
                "status": "error",
                "step": "git push",
                "error": str(fnf),
            }, ensure_ascii=False, indent=2)

        # push 결과 (토큰 노출 방지)
        results.append({
            "cmd": f"git push -u origin {branch_name} --force",
            "returncode": proc.returncode,
            "stdout": proc.stdout.strip(),
            "stderr": _sanitize_token(proc.stderr.strip(), github_token),
        })

        if proc.returncode != 0:
            return json.dumps({
                "status": "error",
                "step": "git push",
                "error": _sanitize_token(proc.stderr.strip(), github_token),
                "completed_steps": results,
            }, ensure_ascii=False, indent=2)

        # ── Step 3: GitHub REST API로 PR 생성 ──
        api_url = f"https://api.github.com/repos/{owner}/{repo}/pulls"
        headers = {
            "Authorization": f"token {github_token}",
            "Accept": "application/vnd.github.v3+json",
        }
        pr_data = {
            "title": f"feat: {feature_name}",
            "body": pr_body,
            "head": branch_name,
            "base": base_branch,
        }

        resp = http_requests.post(api_url, json=pr_data, headers=headers, timeout=30)

        if resp.status_code == 201:
            pr_info = resp.json()
            pr_url = pr_info["html_url"]
            results.append({
                "cmd": f"GitHub API: POST {api_url}",
                "status": "created",
                "pr_url": pr_url,
            })
            return json.dumps({
                "status": "ok",
                "branch": branch_name,
                "pr_url": pr_url,
                "pr_number": pr_info["number"],
                "steps": results,
            }, ensure_ascii=False, indent=2)
        elif resp.status_code == 422:
            # PR이 이미 존재하는 경우
            error_msg = resp.json().get("errors", [{}])[0].get("message", "")
            if "already exists" in error_msg.lower() or "pull request already exists" in error_msg.lower():
                results.append({
                    "cmd": f"GitHub API: POST {api_url}",
                    "status": "already_exists",
                    "message": "PR이 이미 존재합니다.",
                })
                return json.dumps({
                    "status": "ok",
                    "branch": branch_name,
                    "message": "PR이 이미 존재합니다. push는 완료되었습니다.",
                    "steps": results,
                }, ensure_ascii=False, indent=2)
            else:
                return json.dumps({
                    "status": "error",
                    "step": "PR 생성",
                    "error": resp.json(),
                    "completed_steps": results,
                }, ensure_ascii=False, indent=2)
        else:
            return json.dumps({
                "status": "error",
                "step": "PR 생성",
                "error": f"HTTP {resp.status_code}: {resp.text}",
                "completed_steps": results,
            }, ensure_ascii=False, indent=2)

    except Exception as e:
        return json.dumps({"status": "error", "error": str(e)}, ensure_ascii=False)


# ══════════════════════════════════════════
#  Tool 6: 프로젝트 상태 조회
# ══════════════════════════════════════════

@mcp.tool()
def get_project_status(target_path: str) -> str:
    """대상 프로젝트의 .brawl.json 상태와 이전 토론 기록을 조회합니다.

    Args:
        target_path: 대상 프로젝트 경로
    """
    target = os.path.abspath(target_path)
    config = load_config(target)

    if not config:
        return json.dumps({
            "status": "not_initialized",
            "message": "프로젝트가 초기화되지 않았습니다. init_project를 먼저 실행하세요.",
        }, ensure_ascii=False)

    from core.project_config import load_previous_discussions
    previous = load_previous_discussions(target)

    return json.dumps({
        "status": "ok",
        "project": config.project,
        "stack": config.stack,
        "roles": config.roles,
        "rounds": config.rounds,
        "features_done": config.features_done,
        "previous_discussions": [
            {"feature": p["feature"], "summary": p["summary"]}
            for p in previous
        ],
    }, ensure_ascii=False, indent=2)


# ══════════════════════════════════════════
#  헬퍼 함수
# ══════════════════════════════════════════

def _get_github_repo_info(target_path: str, env: dict) -> tuple[str, str]:
    """git remote에서 owner/repo를 추출합니다."""
    try:
        proc = subprocess.run(
            ["git", "remote", "get-url", "origin"],
            cwd=target_path, env=env,
            capture_output=True, text=True, timeout=10,
        )
        url = proc.stdout.strip()
        # https://github.com/owner/repo.git 또는 git@github.com:owner/repo.git
        match = re.search(r'github\.com[:/]([^/]+)/([^/.]+)', url)
        if match:
            return match.group(1), match.group(2)
    except Exception:
        pass
    return "", ""


def _sanitize_token(text: str, token: str) -> str:
    """출력에서 토큰을 마스킹합니다."""
    return text.replace(token, "***")


def _run_cmd(cmd, cwd=None, env=None, ignore_error=False):
    """subprocess 헬퍼. ignore_error=True면 실패해도 무시."""
    try:
        proc = subprocess.run(cmd, cwd=cwd, env=env, capture_output=True, text=True, timeout=30)
        return proc
    except Exception:
        return None


def _load_pr_description(target_path: str, feature_name: str) -> str:
    """토론 결과를 PR description으로 변환합니다."""
    from core.project_config import load_previous_discussions

    discussions = load_previous_discussions(target_path)
    target_disc = None
    for d in discussions:
        if d["feature"] == feature_name:
            target_disc = d
            break

    if not target_disc:
        return f"## feat: {feature_name}\n\nGenerated by Brawl & Build"

    lines = [
        f"## feat: {feature_name}",
        "",
        "### 요약",
        target_disc["summary"],
        "",
        "### 결정 사항",
    ]
    for d in target_disc.get("decisions", []):
        lines.append(f"- {d}")

    lines.extend(["", "### 미해결 과제"])
    for u in target_disc.get("unresolved", []):
        lines.append(f"- {u}")

    lines.extend([
        "",
        "---",
        "*Generated by 🥊 Brawl & Build*",
    ])

    return "\n".join(lines)


# ══════════════════════════════════════════
#  서버 실행
# ══════════════════════════════════════════

if __name__ == "__main__":
    mcp.run(transport="stdio")
