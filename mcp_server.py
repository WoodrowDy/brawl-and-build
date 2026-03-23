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
import subprocess

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
from core.code_generator import save_generated_code

mcp = FastMCP(name="brawl-and-build")


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
    return json.dumps({
        "status": "ok",
        "message": f"프로젝트 '{project_name}' 초기화 완료",
        "config_path": os.path.join(target, ".brawl.json"),
        "config": {
            "project": config.project,
            "stack": config.stack,
            "roles": config.roles,
            "rounds": config.rounds,
        },
    }, ensure_ascii=False, indent=2)


# ══════════════════════════════════════════
#  Tool 2: 토론 실행 (Brawl)
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

    return json.dumps({
        "status": "ok",
        "feature": feature_name,
        "decisions": result.decisions,
        "unresolved": result.unresolved,
        "summary": result.summary,
        "total_rounds": result.total_rounds,
        "discussion_log": [
            {"role": m.role, "round": m.round, "content": m.content}
            for m in result.discussion_log
        ],
        "files": {"markdown": md_path, "json": json_path},
        "cost": tracker.to_dict(),
    }, ensure_ascii=False, indent=2)


# ══════════════════════════════════════════
#  Tool 3: 코드 생성 (Build)
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

    return json.dumps({
        "status": "ok",
        "feature": feature_name,
        "decisions": result.decisions,
        "unresolved": result.unresolved,
        "summary": result.summary,
        "generated_files": saved_files,
        "discussion_files": {"markdown": md_path, "json": json_path},
        "cost": tracker.to_dict(),
    }, ensure_ascii=False, indent=2)


# ══════════════════════════════════════════
#  Tool 4: PR 생성
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
    target = os.path.abspath(target_path)

    # 토론 결과에서 PR description 로드
    pr_body = _load_pr_description(target, feature_name)

    # 브랜치명 생성 (한글 → 영문 변환은 단순 치환)
    branch_name = f"feature/{feature_name}"

    try:
        cmds = [
            ["git", "checkout", "-b", branch_name],
            ["git", "add", "."],
            ["git", "commit", "-m", f"feat: {feature_name} scaffold by brawl-and-build"],
            ["git", "push", "-u", "origin", branch_name],
            ["gh", "pr", "create",
             "--title", f"feat: {feature_name}",
             "--body", pr_body,
             "--base", base_branch],
        ]

        results = []
        for cmd in cmds:
            proc = subprocess.run(
                cmd, cwd=target,
                capture_output=True, text=True, timeout=30,
            )
            results.append({
                "cmd": " ".join(cmd),
                "returncode": proc.returncode,
                "stdout": proc.stdout.strip(),
                "stderr": proc.stderr.strip(),
            })

            if proc.returncode != 0:
                return json.dumps({
                    "status": "error",
                    "step": " ".join(cmd),
                    "error": proc.stderr.strip(),
                    "completed_steps": results,
                }, ensure_ascii=False, indent=2)

        # PR URL 추출
        pr_url = results[-1]["stdout"]

        return json.dumps({
            "status": "ok",
            "branch": branch_name,
            "pr_url": pr_url,
            "steps": results,
        }, ensure_ascii=False, indent=2)

    except Exception as e:
        return json.dumps({"status": "error", "error": str(e)}, ensure_ascii=False)


# ══════════════════════════════════════════
#  Tool 5: 프로젝트 상태 조회
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
