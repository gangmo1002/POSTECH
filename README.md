# Daily Nuclear + AI Slack Bot (Gemma)

매일 전 세계 원자력 + AI 관련 기사를 수집하고, 동향을 요약해 Slack 채널로 보내는 봇입니다.

## 기능
- NewsAPI + Google News RSS 기반 기사 수집
- 원자력/AI 동시 키워드 필터링
- URL 기준 중복 제거
- Gemma 모델(Ollama)로 Top 5 선별 + 요약
- Slack으로 일일 브리핑 전송
- GitHub Actions로 매일 자동 실행

## 1) 사전 준비
1. Slack App 생성 후 Bot Token 발급
2. Bot OAuth Scope에 `chat:write` 추가
3. 봇을 대상 채널에 초대
4. Ollama 설치 + Gemma 모델 준비
   - Ollama: https://ollama.com/download
   - 모델 준비 예시: `ollama pull gemma4`
5. (선택) NewsAPI Key 준비

## 2) 로컬 실행
```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
# .env 값 채우기
python bot/main.py
```

## 3) 환경변수
- `SLACK_BOT_TOKEN` (필수)
- `SLACK_CHANNEL_ID` (필수)
- `NEWS_API_KEY` (선택: 없으면 RSS만 사용)
- `OLLAMA_BASE_URL` (기본: `http://localhost:11434`)
- `GEMMA_MODEL` (기본: `gemma4`)
- `OLLAMA_TIMEOUT_SECONDS` (기본: `180`)
- `MAX_ARTICLES` (기본: `5`)
- `LOOKBACK_HOURS` (기본: `30`)

## 4) GitHub Actions 설정
Repository Settings → Secrets and variables → Actions 에 아래 값 등록:
- `SLACK_BOT_TOKEN`
- `SLACK_CHANNEL_ID`
- `NEWS_API_KEY` (선택)
- `OLLAMA_BASE_URL` (필수: Ollama 서버 접근 가능한 URL)
- `GEMMA_MODEL` (선택)
- `MAX_ARTICLES` (선택)
- `LOOKBACK_HOURS` (선택)

워크플로우 파일: `.github/workflows/daily_brief.yml`
- 기본 스케줄: 매일 23:00 UTC (한국시간 08:00)
- `workflow_dispatch`로 수동 실행 가능

> 참고: GitHub 호스티드 러너에서 `localhost` Ollama는 접근 불가합니다.
> Actions에서 쓰려면 외부에서 접근 가능한 Ollama endpoint가 필요합니다.

## 5) 커스터마이징 포인트
- 키워드 변경: `bot/main.py`의 `KEYWORDS_NUCLEAR`, `KEYWORDS_AI`
- RSS 검색문: `RSS_QUERIES`
- Slack 메시지 포맷: `build_slack_message()`
- 선별 기준/출력 형식: `summarize_articles_with_gemma()` 프롬프트

## 6) Ollama 타임아웃 에러가 날 때
- 먼저 Ollama 서버가 실행 중인지 확인: `ollama serve`
- 모델이 준비됐는지 확인: `ollama list` / 필요시 `ollama pull gemma4`
- 응답이 느리면 `.env`에서 `OLLAMA_TIMEOUT_SECONDS=300` 이상으로 증가
- 그래도 느리면 작은 모델(`gemma2:2b` 등)로 `GEMMA_MODEL` 변경
