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
    "smr",
    "small modular reactor",
    "iaea",
    "uranium",
]

KEYWORDS_AI = [
    "ai",
    "artificial intelligence",
    "machine learning",
    "predictive",
    "digital twin",
]

RSS_QUERIES = [
    "nuclear ai",
    "smr artificial intelligence",
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


def parse_date(raw: str) -> datetime:
    try:
        dt = date_parser.parse(raw)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)
    except Exception:
        return utc_now()


def load_config() -> Dict[str, str]:
    load_dotenv()
    cfg = {
        "slack_bot_token": os.getenv("SLACK_BOT_TOKEN", ""),
        "slack_channel_id": os.getenv("SLACK_CHANNEL_ID", ""),
        "news_api_key": os.getenv("NEWS_API_KEY", ""),
        "max_articles": int(os.getenv("MAX_ARTICLES", "5")),
        "lookback_hours": int(os.getenv("LOOKBACK_HOURS", "30")),
        "use_ollama": os.getenv("USE_OLLAMA", "false").lower() == "true",
        "ollama_base_url": os.getenv("OLLAMA_BASE_URL", "http://localhost:11434"),
        "gemma_model": os.getenv("GEMMA_MODEL", "gemma4"),
        "ollama_timeout_seconds": int(os.getenv("OLLAMA_TIMEOUT_SECONDS", "120")),
    }

    required = ["slack_bot_token", "slack_channel_id"]
    missing = [key for key in required if not cfg[key]]
    if missing:
        raise RuntimeError(f"Missing required environment variables: {', '.join(missing)}")
    return cfg


def contains_topic(text: str) -> bool:
    content = text.lower()
    return any(k in content for k in KEYWORDS_NUCLEAR) and any(k in content for k in KEYWORDS_AI)


def keyword_score(text: str) -> int:
    content = text.lower()
    return sum(k in content for k in KEYWORDS_NUCLEAR) + sum(k in content for k in KEYWORDS_AI)


def fetch_from_newsapi(news_api_key: str, lookback_hours: int) -> List[Article]:
    if not news_api_key:
        return []

    from_dt = (utc_now() - timedelta(hours=lookback_hours)).strftime("%Y-%m-%dT%H:%M:%SZ")
    query = '(nuclear OR reactor OR smr) AND ("artificial intelligence" OR ai OR "machine learning")'

    params = {
        "q": query,
        "language": "en",
        "sortBy": "publishedAt",
        "from": from_dt,
        "pageSize": 20,
        "apiKey": news_api_key,
    }
    try:
        resp = requests.get("https://newsapi.org/v2/everything", params=params, timeout=20)
        resp.raise_for_status()
        data = resp.json()
    except requests.RequestException:
        return []

    items: List[Article] = []
    for raw in data.get("articles", []):
        title = (raw.get("title") or "").strip()
        url = (raw.get("url") or "").strip()
        source = ((raw.get("source") or {}).get("name") or "NewsAPI").strip()
        snippet = (raw.get("description") or "").strip()
        if not title or not url:
            continue
        if not contains_topic(f"{title} {snippet}"):
            continue
        items.append(
            Article(
                title=title,
                url=url,
                source=source,
                published_at=parse_date(raw.get("publishedAt", "")),
                snippet=snippet,
            )
        )
    return items


def fetch_from_rss(lookback_hours: int) -> List[Article]:
    oldest = utc_now() - timedelta(hours=lookback_hours)
    items: List[Article] = []

    for query in RSS_QUERIES:
        url = f"https://news.google.com/rss/search?q={requests.utils.quote(query)}&hl=en-US&gl=US&ceid=US:en"
        feed = feedparser.parse(url)
        for entry in feed.entries:
            title = (entry.get("title") or "").strip()
            link = (entry.get("link") or "").strip()
            source = "Google News"
            if isinstance(entry.get("source"), dict):
                source = (entry.get("source", {}).get("title") or "Google News").strip()
            snippet = (entry.get("summary") or "").strip()
            published = parse_date(entry.get("published", ""))

            if not title or not link or published < oldest:
                continue
            if not contains_topic(f"{title} {snippet}"):
                continue

            items.append(
                Article(
                    title=title,
                    url=link,
                    source=source,
                    published_at=published,
                    snippet=snippet,
                )
            )

    return items


def dedupe(articles: List[Article]) -> List[Article]:
    out: List[Article] = []
    seen = set()
    for article in sorted(articles, key=lambda a: a.published_at, reverse=True):
        key = article.url.split("?")[0].lower()
        if key in seen:
            continue
        seen.add(key)
        out.append(article)
    return out


def rank_articles(articles: List[Article]) -> List[Article]:
    def score(a: Article) -> float:
        age_hours = max((utc_now() - a.published_at).total_seconds() / 3600.0, 0)
        recency = max(0, 24 - min(age_hours, 24)) / 24
        topical = keyword_score(f"{a.title} {a.snippet}") / 10
        return recency + topical

    return sorted(articles, key=score, reverse=True)


def summarize_local(articles: List[Article], max_articles: int) -> Dict:
    selected = articles[:max_articles]
    items = []
    for article in selected:
        snippet = article.snippet.replace("\n", " ").strip()
        one_line = snippet[:180] if snippet else "원문 링크에서 상세 내용을 확인하세요."
        items.append(
            {
                "title": article.title,
                "url": article.url,
                "source": article.source,
                "summary": one_line,
                "why_it_matters": "원자력+AI 연관 이슈로 분류된 기사입니다.",
            }
        )

    return {
        "daily_trend_summary": [
            "최근 원자력+AI 교차 키워드 기사 중심으로 자동 집계했습니다.",
            "모델 실패 시에도 로컬 요약으로 끊김 없이 전송합니다.",
        ],
        "items": items,
    }


def summarize_with_ollama(cfg: Dict[str, str], articles: List[Article]) -> Dict:
    payload = [
        {
            "title": a.title,
            "url": a.url,
            "source": a.source,
            "published_at": a.published_at.isoformat(),
            "snippet": a.snippet,
        }
        for a in articles[:8]
    ]

    prompt = (
        "Return JSON only: {daily_trend_summary: string[], items: [{title,source,url,summary,why_it_matters}]}. "
        f"Pick top {cfg['max_articles']} items from this data:\n{payload}"
    )

    body = {
        "model": cfg["gemma_model"],
        "stream": False,
        "format": "json",
        "messages": [
            {"role": "system", "content": "You summarize nuclear+AI news."},
            {"role": "user", "content": prompt},
        ],
        "options": {"temperature": 0},
    }

    try:
        resp = requests.post(
            f"{cfg['ollama_base_url'].rstrip('/')}/api/chat",
            json=body,
            timeout=cfg["ollama_timeout_seconds"],
        )
        resp.raise_for_status()
        content = (resp.json().get("message", {}).get("content") or "").strip()
        parsed = __import__("json").loads(content)
        if isinstance(parsed, dict) and isinstance(parsed.get("items"), list):
            return parsed
    except Exception:
        pass

    return summarize_local(articles, cfg["max_articles"])


def build_message(summary: Dict, max_articles: int) -> str:
    date_str = utc_now().strftime("%Y-%m-%d")
    lines = [f"🌍 *Daily Nuclear + AI Brief* ({date_str})", ""]

    trends = summary.get("daily_trend_summary", [])
    if trends:
        lines.append("*오늘의 동향 요약*")
        for trend in trends[:3]:
            lines.append(f"• {trend}")
        lines.append("")

    lines.append("*Top 기사*")
    for i, item in enumerate(summary.get("items", [])[:max_articles], start=1):
        title = item.get("title", "제목 없음")
        url = item.get("url", "")
        source = item.get("source", "Unknown")
        summary_line = item.get("summary", "요약 없음")
        why = item.get("why_it_matters", "중요 포인트 없음")

        header = f"*{i}. <{url}|{title}>*" if url else f"*{i}. {title}*"
        lines.extend([header, f"- 출처: {source}", f"- 요약: {summary_line}", f"- 중요 포인트: {why}", ""])

    return "\n".join(lines).strip()


def post_to_slack(token: str, channel: str, text: str) -> None:
    WebClient(token=token).chat_postMessage(channel=channel, text=text)


def run() -> None:
    cfg = load_config()
    collected = fetch_from_newsapi(cfg["news_api_key"], cfg["lookback_hours"])
    collected.extend(fetch_from_rss(cfg["lookback_hours"]))

    ranked = rank_articles(dedupe(collected))
    if not ranked:
        text = "🌍 *Daily Nuclear + AI Brief*\n오늘은 조건에 맞는 기사를 찾지 못했습니다."
        post_to_slack(cfg["slack_bot_token"], cfg["slack_channel_id"], text)
        return

    if cfg["use_ollama"]:
        summary = summarize_with_ollama(cfg, ranked)
    else:
        summary = summarize_local(ranked, cfg["max_articles"])

    message = build_message(summary, cfg["max_articles"])
    post_to_slack(cfg["slack_bot_token"], cfg["slack_channel_id"], message)


if __name__ == "__main__":
    run()
