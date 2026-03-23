# 🥊 Brawl & Build

멀티 에이전트 프로젝트 토론 시스템. PM, BE, FE, Designer 역할의 AI 에이전트들이 프로젝트 기능에 대해 토론하고, 결정사항과 미해결과제를 도출합니다.

## 기술 스택

- **LangGraph**: 토론 흐름 제어 (그래프 기반 멀티 에이전트)
- **LangChain + Anthropic**: Claude 모델 기반 LLM 호출
- **FastAPI**: REST API 서버
- **Pydantic**: 데이터 모델 검증

## 설치

```bash
# 의존성 설치
pip install -r requirements.txt

# 환경변수 설정
cp .env.example .env
# .env 파일에 ANTHROPIC_API_KEY 입력
```

## 실행 방법

### 1. CLI (로컬 테스트)

```bash
# 기본 실행
python cli.py -p "소셜 커머스 플랫폼" -f "회원가입"

# 옵션 지정
python cli.py \
  --project "소셜 커머스 플랫폼" \
  --feature "회원가입" \
  --description "소셜 로그인 포함, 이메일 인증 필수" \
  --rounds 3 \
  --output-dir output
```

### 2. FastAPI 서버

```bash
# 서버 시작
python main.py
# 또는
uvicorn main:app --reload --port 8000
```

API 문서: http://localhost:8000/docs

#### API 엔드포인트

| Method | Path | 설명 |
|--------|------|------|
| GET | `/` | 서버 상태 |
| GET | `/roles` | 기본 역할 목록 |
| POST | `/discuss` | 토론 시작 |

#### 토론 요청 예시

```bash
curl -X POST http://localhost:8000/discuss \
  -H "Content-Type: application/json" \
  -d '{
    "project_description": "소셜 커머스 플랫폼",
    "feature_name": "회원가입",
    "feature_description": "소셜 로그인, 이메일 인증 포함",
    "max_rounds": 2
  }'
```

#### 커스텀 역할로 토론

```bash
curl -X POST http://localhost:8000/discuss \
  -H "Content-Type: application/json" \
  -d '{
    "project_description": "AI 챗봇 서비스",
    "feature_name": "대화 히스토리",
    "roles": [
      {
        "name": "PM",
        "title": "Product Manager",
        "system_prompt": "당신은 PM입니다. 사용자 가치 중심으로 판단하세요.",
        "focus_areas": ["사용자 가치", "MVP"]
      },
      {
        "name": "ML Engineer",
        "title": "Machine Learning Engineer",
        "system_prompt": "당신은 ML 엔지니어입니다. 모델 성능과 데이터 관점에서 의견을 제시하세요.",
        "focus_areas": ["모델 성능", "데이터 파이프라인", "추론 최적화"]
      }
    ],
    "max_rounds": 2
  }'
```

## 출력 형식

토론 완료 시 `output/` 폴더에 자동 저장:

- `discussion_<기능명>_<timestamp>.md` - 마크다운 보고서
- `discussion_<기능명>_<timestamp>.json` - 구조화된 JSON

### 결과물 구조

```
1. 프롬프트 - 토론에 사용된 설정 정보
2. 토론 내용 - 라운드별 각 역할의 발언
3. 결과물 - 합의된 결정 사항
4. 미해결 과제 - 추가 논의가 필요한 항목
5. 요약 - 전체 토론 요약
```

## 프로젝트 구조

```
brawl-and-build/
├── main.py              # FastAPI 서버
├── cli.py               # CLI 실행 스크립트
├── requirements.txt
├── .env.example
├── config/
│   └── roles.py         # 기본 역할 정의
├── core/
│   ├── state.py         # LangGraph 상태 정의
│   ├── agents.py        # 에이전트 노드 생성
│   ├── graph.py         # 토론 그래프 구성
│   ├── summarizer.py    # 결과 정리 에이전트
│   └── exporter.py      # MD/JSON 내보내기
├── models/
│   └── schemas.py       # Pydantic 모델
└── output/              # 토론 결과 저장
```

## 역할 커스터마이징

`config/roles.py`에서 기본 역할을 수정하거나, API 호출 시 `roles` 파라미터로 커스텀 역할을 전달할 수 있습니다.
