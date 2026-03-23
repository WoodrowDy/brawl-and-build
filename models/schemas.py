"""Pydantic models for the discussion system."""

from pydantic import BaseModel, Field
from enum import Enum


class RoleType(str, Enum):
    PM = "PM"
    BE = "BE"
    FE = "FE"
    DESIGNER = "Designer"
    CUSTOM = "Custom"


class RoleConfig(BaseModel):
    """역할 설정 - 사용자가 커스텀 가능"""
    name: str = Field(description="역할 이름 (예: PM, BE, FE, Designer)")
    title: str = Field(description="역할 직함 (예: Product Manager)")
    system_prompt: str = Field(description="역할의 성격과 관점을 정의하는 시스템 프롬프트")
    focus_areas: list[str] = Field(description="이 역할이 주로 신경쓰는 영역들")


class DiscussionMessage(BaseModel):
    """토론 중 하나의 발언"""
    role: str
    round: int
    content: str


class FeatureSpec(BaseModel):
    """하나의 기능 명세"""
    name: str
    description: str
    decisions: list[str] = Field(default_factory=list, description="결정된 사항들")
    unresolved: list[str] = Field(default_factory=list, description="미해결 과제들")


class DiscussionRequest(BaseModel):
    """토론 요청 (API 입력)"""
    project_description: str = Field(description="프로젝트 설명")
    feature_name: str = Field(description="논의할 기능 이름")
    feature_description: str = Field(default="", description="기능에 대한 추가 설명")
    roles: list[RoleConfig] | None = Field(default=None, description="커스텀 역할 목록 (None이면 기본 4역할)")
    max_rounds: int = Field(default=3, ge=1, le=10, description="토론 라운드 수")


class DiscussionResult(BaseModel):
    """토론 결과 (API 출력)"""
    project_description: str
    feature_name: str
    prompt_used: str = Field(description="토론에 사용된 프롬프트")
    discussion_log: list[DiscussionMessage] = Field(description="전체 토론 내용")
    decisions: list[str] = Field(description="결정된 사항들")
    unresolved: list[str] = Field(description="미해결 과제들")
    summary: str = Field(description="토론 요약")
    total_rounds: int
