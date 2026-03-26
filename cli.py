"""CLI 실행 스크립트 - 터미널에서 바로 토론을 돌려볼 수 있습니다."""

import sys
import os
import argparse

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from dotenv import load_dotenv

load_dotenv()

from core.graph import run_discussion
from core.exporter import state_to_result, export_markdown, export_json
from core.cost_tracker import track_cost
from core.code_generator import scaffold_project
from core.project_config import (
    load_config, save_config, init_config,
    mark_feature_done, build_previous_context, ProjectConfig,
)


def main():
    parser = argparse.ArgumentParser(
        description="🥊 Brawl & Build - 멀티 에이전트 프로젝트 토론 시스템"
    )
    parser.add_argument(
        "--project", "-p",
        type=str,
        default=None,
        help="프로젝트 설명 (.brawl.json 있으면 생략 가능)"
    )
    parser.add_argument(
        "--feature", "-f",
        type=str,
        default=None,
        help="토론할 기능 이름 (예: '회원가입')"
    )
    parser.add_argument(
        "--description", "-d",
        type=str,
        default="",
        help="기능에 대한 추가 설명"
    )
    parser.add_argument(
        "--rounds", "-r",
        type=int,
        default=None,
        help="토론 라운드 수 (.brawl.json 기본값 또는 2)"
    )
    parser.add_argument(
        "--build", "-b",
        action="store_true",
        default=False,
        help="토론 후 코드 생성 (Build 페이즈) 활성화"
    )
    parser.add_argument(
        "--output-dir", "-o",
        type=str,
        default="output",
        help="결과물 저장 디렉토리 (기본: output)"
    )
    parser.add_argument(
        "--generated-dir", "-g",
        type=str,
        default="generated",
        help="생성된 코드 저장 디렉토리 (기본: generated)"
    )
    parser.add_argument(
        "--target", "-t",
        type=str,
        default=None,
        help="대상 프로젝트 경로 (지정 시 해당 repo에 코드 생성)"
    )
    parser.add_argument(
        "--init",
        action="store_true",
        default=False,
        help="대상 프로젝트에 .brawl.json 초기화"
    )

    args = parser.parse_args()

    # ── 설정 파일 로드 ──
    config = None
    previous_context = ""
    target_dir = os.path.abspath(args.target) if args.target else None

    if target_dir:
        config = load_config(target_dir)

        if args.init:
            project_name = args.project or "My Project"
            config = init_config(target_dir, project_name)
            print(f"✅ .brawl.json 초기화 완료 → {target_dir}")

            # 프로젝트 scaffold (nest new, create-vite) - 최초 1회
            print("🏗️  프로젝트 scaffold 생성 중...")
            scaffold_result = scaffold_project(target_dir)
            if scaffold_result.get("skipped"):
                print("⏭️  이미 scaffold가 존재합니다. 건너뜁니다.")
            else:
                print("✅ scaffold 생성 완료 (NestJS + React + Shared)")

            if not args.feature:
                return

        if config:
            print(f"📂 설정 파일 로드: {target_dir}/.brawl.json")
            # 이전 토론 컨텍스트 로드
            previous_context = build_previous_context(target_dir)
            if previous_context:
                print(f"🔗 이전 토론 {len(config.features_done)}건 컨텍스트 연결")

    # --init만 실행한 경우 여기서 종료
    if not args.feature:
        if not args.init:
            print("❌ --feature 옵션이 필요합니다. (예: --feature '회원가입')")
            sys.exit(1)
        return

    # CLI 인자 > 설정 파일 > 기본값
    project_name = args.project or (config.project if config else None)
    if not project_name:
        print("❌ --project 또는 .brawl.json의 project 필드가 필요합니다.")
        sys.exit(1)

    max_rounds = args.rounds or (config.rounds if config else 2)

    print("=" * 60)
    print("🥊 Brawl & Build - 토론 시작!")
    print("=" * 60)
    print(f"📋 프로젝트: {project_name}")
    print(f"🎯 기능: {args.feature}")
    print(f"🔄 라운드: {max_rounds}")
    print(f"🔨 빌드: {'ON' if args.build else 'OFF'}")
    if target_dir:
        print(f"🎯 대상: {target_dir}")
    print("=" * 60)
    print()

    # 토론 실행 (비용 추적 포함)
    phase = "토론 + 코드 생성" if args.build else "토론"
    print(f"⏳ {phase} 진행 중... (시간이 걸릴 수 있습니다)")
    print()

    with track_cost() as tracker:
        final_state = run_discussion(
            project_description=project_name,
            feature_name=args.feature,
            feature_description=args.description,
            max_rounds=max_rounds,
            enable_build=args.build,
            previous_context=previous_context,
        )

    # 결과 출력
    result = state_to_result(final_state)

    print("\n" + "=" * 60)
    print("📝 토론 내용")
    print("=" * 60)

    current_round = None
    for msg in result.discussion_log:
        if msg.round != current_round:
            current_round = msg.round
            print(f"\n--- 라운드 {current_round} ---\n")
        print(f"💬 [{msg.role}]:")
        print(f"   {msg.content}\n")

    print("\n" + "=" * 60)
    print("✅ 결정 사항")
    print("=" * 60)
    for i, d in enumerate(result.decisions, 1):
        print(f"  {i}. {d}")

    print("\n" + "=" * 60)
    print("❓ 미해결 과제")
    print("=" * 60)
    for i, u in enumerate(result.unresolved, 1):
        print(f"  {i}. {u}")

    print("\n" + "=" * 60)
    print("📄 요약")
    print("=" * 60)
    print(f"  {result.summary}")

    # 파일 저장
    md_path = export_markdown(result, output_dir=args.output_dir)
    json_path = export_json(result, output_dir=args.output_dir)

    print("\n" + "=" * 60)
    print("💾 파일 저장 완료")
    print("=" * 60)
    print(f"  📝 Markdown: {md_path}")
    print(f"  📊 JSON: {json_path}")

    # Build 결과 저장
    if args.build and final_state.get("build_outputs"):
        from core.code_generator import save_generated_code

        code_output_dir = args.generated_dir
        if target_dir:
            code_output_dir = target_dir
            print(f"\n  🎯 대상 프로젝트: {code_output_dir}")

        saved_files = save_generated_code(final_state, output_dir=code_output_dir)

        # 토론 결과도 대상 프로젝트 docs/에 저장
        if target_dir:
            docs_dir = os.path.join(code_output_dir, "docs", "discussions")
            export_markdown(result, output_dir=docs_dir)
            export_json(result, output_dir=docs_dir)
            print(f"  📝 토론 기록 → {docs_dir}/")

            # .brawl.json에 완료 기능 기록
            mark_feature_done(target_dir, args.feature)
            print(f"  ✅ '{args.feature}' → .brawl.json features_done에 기록")

        print("\n" + "=" * 60)
        print("🔨 생성된 코드")
        print("=" * 60)
        for f in saved_files:
            print(f"  📄 {f}")
        print(f"\n  총 {len(saved_files)}개 파일 생성 → {code_output_dir}/")

    # 비용 리포트 출력
    print(tracker.summary())
    print(tracker.detail_summary())


if __name__ == "__main__":
    main()
