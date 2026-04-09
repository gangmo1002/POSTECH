import hashlib
import hmac
import os
import threading
import time
from typing import Dict, List, Tuple

from dotenv import load_dotenv
from flask import Flask, jsonify, request

from bot.main import (
    build_blocks,
    build_fallback_text,
    dedupe_articles,
    fetch_from_google_rss,
    fetch_from_newsapi,
    load_config,
    post_to_slack,
    rank_articles,
    summarize_article,
    summarize_trends,
)

app = Flask(__name__)


def verify_slack_signature(signing_secret: str, body: bytes, timestamp: str, signature: str) -> bool:
    if not signing_secret:
        return True
    if not timestamp or not signature:
        return False

    try:
        ts = int(timestamp)
    except ValueError:
        return False

    if abs(int(time.time()) - ts) > 60 * 5:
        return False

    base = f"v0:{timestamp}:{body.decode('utf-8')}".encode("utf-8")
    computed = "v0=" + hmac.new(signing_secret.encode("utf-8"), base, hashlib.sha256).hexdigest()
    return hmac.compare_digest(computed, signature)


def generate_brief_for_channel(channel_id: str) -> None:
    cfg = load_config()

    collected = fetch_from_newsapi(str(cfg["news_api_key"]), int(cfg["lookback_hours"]))
    collected.extend(fetch_from_google_rss(int(cfg["lookback_hours"])))

    ranked = rank_articles(dedupe_articles(collected))
    top_articles = ranked[: max(5, int(cfg["max_articles"]) * 2)]

    if not top_articles:
        post_to_slack(
            token=str(cfg["slack_bot_token"]),
            channel=channel_id,
            text="Daily Nuclear Brief\n조건에 맞는 공신력 원자력 기사를 찾지 못했습니다.",
            blocks=[],
        )
        return

    selected = top_articles[: int(cfg["max_articles"])]
    summarized: List[Dict[str, object]] = [summarize_article(cfg, article) for article in selected]
    trends = summarize_trends(cfg, summarized)

    text = build_fallback_text(summarized, trends)
    blocks = build_blocks(trends, summarized)
    post_to_slack(
        token=str(cfg["slack_bot_token"]),
        channel=channel_id,
        text=text,
        blocks=blocks,
    )


@app.post("/slack/commands")
def slack_commands() -> Tuple[str, int] | Tuple[Dict[str, str], int]:
    load_dotenv()
    signing_secret = os.getenv("SLACK_SIGNING_SECRET", "")

    raw_body = request.get_data()
    timestamp = request.headers.get("X-Slack-Request-Timestamp", "")
    signature = request.headers.get("X-Slack-Signature", "")

    if not verify_slack_signature(signing_secret, raw_body, timestamp, signature):
        return jsonify({"text": "Signature verification failed."}), 401

    form = request.form
    command = (form.get("command") or "").strip()
    channel_id = (form.get("channel_id") or "").strip()

    if command != "/nuclear-brief":
        return jsonify({"response_type": "ephemeral", "text": "지원되지 않는 명령입니다."}), 200

    if not channel_id:
        return jsonify({"response_type": "ephemeral", "text": "채널 정보를 확인할 수 없습니다."}), 200

    def job() -> None:
        try:
            generate_brief_for_channel(channel_id)
        except Exception:
            # last resort: do not crash the web server
            cfg = load_config()
            post_to_slack(
                token=str(cfg["slack_bot_token"]),
                channel=channel_id,
                text="Daily Nuclear Brief\n요청 처리 중 오류가 발생했습니다. 잠시 후 다시 시도해 주세요.",
                blocks=[],
            )

    threading.Thread(target=job, daemon=True).start()

    return (
        jsonify(
            {
                "response_type": "ephemeral",
                "text": "요청 접수 완료 ✅ 잠시 후 이 채널에 최신 원자력 Top 5를 보내드릴게요.",
            }
        ),
        200,
    )


if __name__ == "__main__":
    port = int(os.getenv("PORT", "3000"))
    app.run(host="0.0.0.0", port=port)
