"""프로젝트 설정 파일 (.brawl.json) 관리.

대상 프로젝트 루트에 .brawl.json을 두면,
매번 CLI 옵션을 반복 입력하지 않아도 됩니다.
"""

import json
import os
from dataclasses import dataclass, field, asdict
from models.schemas import RoleConfig


@dataclass
class ProjectConfig:
    """프로젝트 설정"""

    project: str = ""
    stack: dict = field(default_factory=lambda: {
        "backend": "nestjs",
        "frontend": "react-ts",
        "monorepo": "lerna",
    })
    roles: list[str] = field(default_factory=lambda: ["PM", "BE", "FE", "Designer"])
    rounds: int = 2
    model: str = "claude-sonnet-4-20250514"
    features_done: list[str] = field(default_factory=list)


CONFIG_FILENAME = ".brawl.json"


def load_config(target_dir: str) -> ProjectConfig | None:
    """대상 프로젝트에서 .brawl.json을 로드합니다."""
    config_path = os.path.join(target_dir, CONFIG_FILENAME)
    if not os.path.exists(config_path):
        return None

    with open(config_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    return ProjectConfig(**data)


def save_config(config: ProjectConfig, target_dir: str) -> str:
    """대상 프로젝트에 .brawl.json을 저장합니다."""
    config_path = os.path.join(target_dir, CONFIG_FILENAME)
    os.makedirs(target_dir, exist_ok=True)

    with open(config_path, "w", encoding="utf-8") as f:
        json.dump(asdict(config), f, ensure_ascii=False, indent=2)

    return config_path


def init_config(target_dir: str, project_name: str = "") -> ProjectConfig:
    """새 프로젝트 설정을 초기화합니다."""
    config = ProjectConfig(project=project_name)
    save_config(config, target_dir)
    return config


def mark_feature_done(target_dir: str, feature_name: str):
    """완료된 기능을 설정 파일에 기록합니다."""
    config = load_config(target_dir)
    if config is None:
        return

    if feature_name not in config.features_done:
        config.features_done.append(feature_name)
        save_config(config, target_dir)


def load_previous_discussions(target_dir: str) -> list[dict]:
    """이전 토론 결과(JSON)를 로드하여 컨텍스트로 사용합니다."""
    docs_dir = os.path.join(target_dir, "docs", "discussions")
    if not os.path.exists(docs_dir):
        return []

    previous = []
    for filename in sorted(os.listdir(docs_dir)):
        if filename.endswith(".json"):
            filepath = os.path.join(docs_dir, filename)
            with open(filepath, "r", encoding="utf-8") as f:
                data = json.load(f)
                previous.append({
                    "feature": data.get("feature_name", ""),
                    "decisions": data.get("decisions", []),
                    "unresolved": data.get("unresolved", []),
                    "summary": data.get("summary", ""),
                })

    return previous


def build_previous_context(target_dir: str) -> str:
    """이전 토론 내용을 프롬프트 컨텍스트 문자열로 변환합니다."""
    previous = load_previous_discussions(target_dir)
    if not previous:
        return ""

    lines = ["## 이전에 토론한 기능들"]
    for p in previous:
        lines.append(f"\n### {p['feature']}")
        lines.append(f"요약: {p['summary']}")
        if p["decisions"]:
            lines.append("결정사항:")
            for d in p["decisions"]:
                lines.append(f"  - {d}")
        if p["unresolved"]:
            lines.append("미해결:")
            for u in p["unresolved"]:
                lines.append(f"  - {u}")

    return "\n".join(lines)
