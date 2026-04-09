# Daily Nuclear + AI Slack Bot (Lightweight)

매일 전 세계 원자력 + AI 관련 기사를 모아서 Slack에 보내는 가벼운 봇입니다.

## 특징
- 기본 모드: **LLM 없이** 기사 제목/스니펫 기반 요약 (빠르고 안정적)
- 선택 모드: `USE_OLLAMA=true`일 때만 Gemma(Ollama) 사용
- NewsAPI + Google News RSS 수집
- 키워드 필터 + 중복 제거 + 간단 랭킹
- GitHub Actions 스케줄 실행 지원

## 로컬 실행
```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
# .env 값 채우기
python bot/main.py
```

## 환경변수
- `SLACK_BOT_TOKEN` (필수)
- `SLACK_CHANNEL_ID` (필수)
- `NEWS_API_KEY` (선택)
- `USE_OLLAMA` (기본: `false`)
- `OLLAMA_BASE_URL` (기본: `http://localhost:11434`)
- `GEMMA_MODEL` (기본: `gemma4`)
- `OLLAMA_TIMEOUT_SECONDS` (기본: `120`)
- `MAX_ARTICLES` (기본: `5`)
- `LOOKBACK_HOURS` (기본: `30`)

## 추천 설정 (안정성 우선)
- 우선 `USE_OLLAMA=false`로 돌리기
- 안정적으로 돌아가면 그때 `USE_OLLAMA=true` 전환
- Ollama 느리면 `OLLAMA_TIMEOUT_SECONDS=300`으로 증가

## GitHub Actions 주의
- 기본 스케줄: 매일 23:00 UTC (한국시간 08:00)
- GitHub 호스티드 러너는 `localhost` Ollama 접근 불가
- Actions에서 Ollama를 쓰려면 외부 접근 가능한 `OLLAMA_BASE_URL` 필요
