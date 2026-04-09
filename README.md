# Daily Nuclear + AI Slack Bot (LLM + Trusted Sources)

매일 전 세계 원자력 + AI 관련 기사를 모아서 Slack에 보내는 가벼운 봇입니다.

## 특징
- Gemma(Ollama) 기반 한줄 요약 생성
- NewsAPI + Google News RSS 수집
- 키워드 필터 + 중복 제거 + 간단 랭킹
- Reuters/AP/Bloomberg/FT/WSJ/BBC/CNBC/NYT/Economist/IAEA 등 **공신력 소스 우선**
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
- `OLLAMA_BASE_URL` (기본: `http://localhost:11434`)
- `GEMMA_MODEL` (기본: `gemma4`)
- `OLLAMA_TIMEOUT_SECONDS` (기본: `180`)
- `MAX_ARTICLES` (기본: `5`)
- `LOOKBACK_HOURS` (기본: `30`)

## 추천 설정 (안정성 우선)
- Ollama 서버 먼저 실행: `ollama serve`
- 모델 준비: `ollama pull gemma4`
- Ollama 느리면 `OLLAMA_TIMEOUT_SECONDS=300`으로 증가

## GitHub Actions 주의
- 기본 스케줄: 매일 23:00 UTC (한국시간 08:00)
- GitHub 호스티드 러너는 `localhost` Ollama 접근 불가
- Actions에서 Ollama를 쓰려면 외부 접근 가능한 `OLLAMA_BASE_URL` 필요
