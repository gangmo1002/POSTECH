import json
import os
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Dict, List

import feedparser
import requests
from dateutil import parser as date_parser
from dotenv import load_dotenv
from slack_sdk import WebClient


KEYWORDS_NUCLEAR = [
    "nuclear",
    "reactor",
    "small modular reactor",
    "smr",
    "nuclear plant",
    "nuclear energy",
    "iaea",
]

KEYWORDS_AI = [
    "ai",
    "artificial intelligence",
    "machine learning",
    "deep learning",
    "digital twin",
    "predictive maintenance",
    "computer vision",
]

RSS_QUERIES = [
    "nuclear AI",
    "small modular reactor artificial intelligence",
    "nuclear predictive maintenance",
]


@dataclass
class Article:
    title: str
    url: str
    source: str
    published_at: datetime
    snippet: str


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def load_config() -> Dict[str, str]:
    load_dotenv()
    cfg = {
        "slack_bot_token": os.getenv("SLACK_BOT_TOKEN", ""),
        "slack_channel_id": os.getenv("SLACK_CHANNEL_ID", ""),
        "news_api_key": os.getenv("NEWS_API_KEY", ""),
        "max_articles": int(os.getenv("MAX_ARTICLES", "5")),
        "lookback_hours": int(os.getenv("LOOKBACK_HOURS", "30")),
        "ollama_base_url": os.getenv("OLLAMA_BASE_URL", "http://localhost:11434"),
        "gemma_model": os.getenv("GEMMA_MODEL", "gemma4"),
    }

    required = ["slack_bot_token", "slack_channel_id"]
    missing = [k for k in required if not cfg[k]]
    if missing:
        raise RuntimeError(f"Missing required environment variables: {', '.join(missing)}")

    return cfg


def contains_keywords(text: str) -> bool:
    lower = text.lower()
    nuclear_hit = any(k in lower for k in KEYWORDS_NUCLEAR)
    ai_hit = any(k in lower for k in KEYWORDS_AI)
    return nuclear_hit and ai_hit


def parse_date(raw: str) -> datetime:
    try:
        dt = date_parser.parse(raw)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)
    except Exception:
        return utc_now()


def fetch_from_newsapi(news_api_key: str, lookback_hours: int) -> List[Article]:
    if not news_api_key:
        return []

    from_dt = (utc_now() - timedelta(hours=lookback_hours)).strftime("%Y-%m-%dT%H:%M:%SZ")
    query = '(nuclear OR reactor OR "small modular reactor" OR IAEA) AND ("artificial intelligence" OR AI OR "machine learning" OR "predictive maintenance")'

    params = {
        "q": query,
        "language": "en",
        "sortBy": "publishedAt",
        "from": from_dt,
        "pageSize": 50,
        "apiKey": news_api_key,
    }
    resp = requests.get("https://newsapi.org/v2/everything", params=params, timeout=30)
    resp.raise_for_status()
    data = resp.json()

    results: List[Article] = []
    for item in data.get("articles", []):
        title = item.get("title", "").strip()
        url = item.get("url", "").strip()
        source = (item.get("source") or {}).get("name", "Unknown")
        snippet = (item.get("description") or "").strip()
        if not title or not url:
            continue
        text_blob = f"{title} {snippet}"
        if not contains_keywords(text_blob):
            continue
        results.append(
            Article(
                title=title,
                url=url,
                source=source,
                published_at=parse_date(item.get("publishedAt", "")),
                snippet=snippet,
            )
        )
    return results


def fetch_from_google_news_rss(lookback_hours: int) -> List[Article]:
    results: List[Article] = []
    oldest = utc_now() - timedelta(hours=lookback_hours)

    for q in RSS_QUERIES:
        url = f"https://news.google.com/rss/search?q={requests.utils.quote(q)}&hl=en-US&gl=US&ceid=US:en"
        feed = feedparser.parse(url)
        for entry in feed.entries:
            title = entry.get("title", "").strip()
            link = entry.get("link", "").strip()
            source = entry.get("source", {}).get("title", "Google News") if isinstance(entry.get("source"), dict) else "Google News"
            snippet = (entry.get("summary", "") or "").strip()
            published = parse_date(entry.get("published", ""))

            if not title or not link:
                continue
            if published < oldest:
                continue
            if not contains_keywords(f"{title} {snippet}"):
                continue

            results.append(
                Article(
                    title=title,
                    url=link,
                    source=source,
                    published_at=published,
                    snippet=snippet,
                )
            )

    return results


def dedupe_articles(articles: List[Article]) -> List[Article]:
    seen = set()
    out: List[Article] = []
    for article in sorted(articles, key=lambda a: a.published_at, reverse=True):
        key = article.url.split("?")[0].strip().lower()
        fallback = article.title.strip().lower()
        dedupe_key = key or fallback
        if dedupe_key in seen:
            continue
        seen.add(dedupe_key)
        out.append(article)
    return out


def summarize_articles_with_gemma(
    ollama_base_url: str,
    gemma_model: str,
    articles: List[Article],
    max_articles: int,
) -> Dict:
    payload = [
        {
            "title": a.title,
            "url": a.url,
            "source": a.source,
            "published_at": a.published_at.isoformat(),
            "snippet": a.snippet,
        }
        for a in articles
    ]

    system_prompt = (
        "You are an analyst focused on global nuclear + AI developments. "
        "Return JSON only. No markdown."
    )

    user_prompt = f"""
Select top {max_articles} most relevant and impactful items from the article list.

Return valid JSON with this schema:
{{
  "daily_trend_summary": ["5 bullet lines max, plain text"],
  "items": [
    {{
      "title": "string",
      "source": "string",
      "url": "string",
      "why_it_matters": "one short sentence",
      "summary": "2-3 short sentences"
    }}
  ]
}}

Selection priorities:
1) Nuclear + AI both clearly present
2) Policy, deployment, investment, safety or technical breakthroughs
3) Geographic diversity
4) Recency

Article data:
{json.dumps(payload, ensure_ascii=False)}
""".strip()

    body = {
        "model": gemma_model,
        "stream": False,
        "format": "json",
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
    }

    base = ollama_base_url.rstrip("/")
    resp = requests.post(f"{base}/api/chat", json=body, timeout=180)
    resp.raise_for_status()

    data = resp.json()
    content = data.get("message", {}).get("content", "").strip()
    if not content:
        raise RuntimeError("Gemma response is empty. Check OLLAMA_BASE_URL/GEMMA_MODEL.")

    return json.loads(content)


def build_slack_message(summary: Dict) -> str:
    date_str = utc_now().strftime("%Y-%m-%d")
    lines = [f"🌍 *Daily Nuclear + AI Brief* ({date_str})", ""]

    trend_lines = summary.get("daily_trend_summary", [])
    if trend_lines:
        lines.append("*오늘의 동향 요약*")
        for t in trend_lines:
            lines.append(f"• {t}")
        lines.append("")

    lines.append("*Top 5 기사*")
    for idx, item in enumerate(summary.get("items", []), start=1):
        lines.append(f"*{idx}. <{item['url']}|{item['title']}>*")
        lines.append(f"- 출처: {item['source']}")
        lines.append(f"- 요약: {item['summary']}")
        lines.append(f"- 중요 포인트: {item['why_it_matters']}")
        lines.append("")

    return "\n".join(lines).strip()


def post_to_slack(token: str, channel: str, text: str) -> None:
    client = WebClient(token=token)
    client.chat_postMessage(channel=channel, text=text)


def run() -> None:
    cfg = load_config()
    collected: List[Article] = []

    collected.extend(fetch_from_newsapi(cfg["news_api_key"], cfg["lookback_hours"]))
    collected.extend(fetch_from_google_news_rss(cfg["lookback_hours"]))

    filtered = dedupe_articles(collected)
    if not filtered:
        fallback_text = (
            "🌍 *Daily Nuclear + AI Brief*\n"
            "오늘은 조건에 맞는 기사를 찾지 못했습니다. 검색 조건이나 lookback 시간을 늘려보세요."
        )
        post_to_slack(cfg["slack_bot_token"], cfg["slack_channel_id"], fallback_text)
        return

    summary = summarize_articles_with_gemma(
        cfg["ollama_base_url"],
        cfg["gemma_model"],
        filtered,
        cfg["max_articles"],
    )
    message = build_slack_message(summary)
    post_to_slack(cfg["slack_bot_token"], cfg["slack_channel_id"], message)


if __name__ == "__main__":
    run()
