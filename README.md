# Daily Nuclear Brief Bot (Ollama Gemma)

매일 원자력 글로벌 뉴스 Top 5를 Slack으로 보내는 최소구현 봇입니다.

## 핵심 특징
- NewsAPI + Google News RSS 수집
- 공신력 매체 우선 필터링
- 기사별 개별 Gemma 요약 (한줄요약 + 핵심내용 최대 3개)
- 마지막에 간단 동향 요약 생성(실패 시 생략)
- Gemma timeout / non-JSON / empty response 시에도 fallback으로 Slack 전송 유지
- Slack Block Kit + unfurl 비활성화
- Slack Slash Command(`/nuclear-brief`)로 수동 요청 가능

## 지원 소스 (우선)
Reuters, AP News, Bloomberg, Financial Times, WSJ, BBC, CNBC,
New York Times, Economist, IAEA, World Nuclear News,
Nuclear Engineering International, POWER Magazine

---

## 1) 설치 (Windows 기준)
```bat
cd C:\AI\POSTECH
py -m pip install --upgrade pip
py -m pip install -r requirements.txt
```

## 2) 환경변수 설정
```bat
copy .env.example .env
notepad .env
```

`.env`에 아래 값 입력:
- `SLACK_BOT_TOKEN` (필수)
- `SLACK_CHANNEL_ID` (필수: 스케줄 실행 기본 채널)
- `SLACK_SIGNING_SECRET` (필수: Slash Command 서명 검증용)
- `NEWS_API_KEY` (선택, 없어도 RSS로 동작)
- `OLLAMA_BASE_URL` (기본 `http://localhost:11434`)
- `GEMMA_MODEL` (기본 `gemma4:31b`)
- `MAX_ARTICLES` (기본 `5`)
- `LOOKBACK_HOURS` (기본 `30`)
- `OLLAMA_TIMEOUT_SECONDS` (기본 `300`)
- `PORT` (기본 `3000`)

## 3) Ollama 준비
```bat
ollama serve
```
다른 터미널에서:
```bat
ollama pull gemma4:31b
ollama list
```

## 4) 일회 실행 (스케줄/수동 테스트용)
```bat
py bot\main.py
```

## 5) Slack Slash Command로 요청 실행
서버 실행:
```bat
py bot\server.py
```

Slack App 설정:
1. Slack App > **Slash Commands** > Create New Command
2. Command: `/nuclear-brief`
3. Request URL: `https://<your-public-url>/slack/commands`
4. 앱 재설치(Install/Reinstall) 후 채널에 봇 초대

요청 사용:
- Slack 채널에서 `/nuclear-brief`
- 즉시 "요청 접수" 응답 후, 잠시 뒤 해당 채널에 Top 5 전송

> 로컬 PC에서 테스트하려면 ngrok 같은 터널로 외부 URL을 Slack에 연결하세요.

---

## 장애 대응
- Gemma 응답이 비정상(JSON 아님/비어있음/timeout)이어도 앱이 중단되지 않고 snippet 기반 fallback 요약으로 전송됩니다.
- NewsAPI 키가 없어도 Google RSS로 동작합니다.

## GitHub Actions 참고
- 스케줄 실행은 `.github/workflows/daily_brief.yml` 사용
- GitHub hosted runner에서 `localhost` Ollama는 접근 불가하므로 외부 접근 가능한 Ollama endpoint 필요
