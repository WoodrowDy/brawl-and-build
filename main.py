"""FastAPI 서버 - 토론 시스템 API."""

import sys
import os

# 프로젝트 루트를 PYTHONPATH에 추가
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from dotenv import load_dotenv

from models.schemas import DiscussionRequest, DiscussionResult, RoleConfig
from config.roles import DEFAULT_ROLES
from core.graph import run_discussion
from core.exporter import state_to_result, export_markdown, export_json

load_dotenv()

app = FastAPI(
    title="Brawl & Build",
    description="멀티 에이전트 프로젝트 토론 시스템 - PM, BE, FE, Designer가 기능을 토론합니다.",
    version="0.1.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/")
async def root():
    return {"message": "Brawl & Build - 멀티 에이전트 토론 시스템", "version": "0.1.0"}


@app.get("/roles")
async def get_default_roles() -> list[RoleConfig]:
    """기본 역할 목록을 반환합니다."""
    return DEFAULT_ROLES


@app.post("/discuss", response_model=DiscussionResult)
async def start_discussion(request: DiscussionRequest):
    """토론을 시작하고 결과를 반환합니다."""
    try:
        final_state = run_discussion(
            project_description=request.project_description,
            feature_name=request.feature_name,
            feature_description=request.feature_description,
            roles=request.roles,
            max_rounds=request.max_rounds,
        )

        result = state_to_result(final_state)

        # Markdown + JSON 파일 자동 저장
        md_path = export_markdown(result)
        json_path = export_json(result)

        print(f"✅ Markdown 저장: {md_path}")
        print(f"✅ JSON 저장: {json_path}")

        return result

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/discuss/stream")
async def start_discussion_stream(request: DiscussionRequest):
    """(향후 구현) SSE 스트리밍으로 토론 과정을 실시간 전달합니다."""
    raise HTTPException(status_code=501, detail="스트리밍 기능은 아직 구현되지 않았습니다.")


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)
