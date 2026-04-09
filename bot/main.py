import json
import os
import re
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from html import unescape
from typing import Dict, List, Optional

import feedparser
import requests
from dateutil import parser as date_parser
from dotenv import load_dotenv
from slack_sdk import WebClient

# ----------------------------
# Source quality configuration
# ----------------------------
TRUSTED_SOURCES = {
    "Reuters": 10,
    "AP News": 9,
    "Bloomberg": 9,
    "Financial Times": 9,
    "The Wall Street Journal": 9,
    "BBC": 8,
    "CNBC": 8,
    "The New York Times": 8,
    "The Economist": 8,
    "IAEA": 10,
    "World Nuclear News": 9,
    "Nuclear Engineering International": 8,
    "POWER Magazine": 8,
}

TRUSTED_DOMAINS = [
    "reuters.com",
    "apnews.com",
    "bloomberg.com",
    "ft.com",
    "wsj.com",
    "bbc.com",
    "cnbc.com",
    "nytimes.com",
    "economist.com",
    "iaea.org",
    "world-nuclear-news.org",
    "neimagazine.com",
    "powermag.com",
]

BLOCKLIST_PATTERNS = [
    "support.google.com",
    "google help",
    "how to",
    "guide",
    "tutorial",
    "help center",
    "customer support",
]

RSS_QUERIES = [
    "nuclear energy",
    "nuclear reactor",
    "small modular reactor",
    "nuclear policy",
    "iaea nuclear",
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


def clean_text(raw: str, max_len: int = 350) -> str:
    text = unescape(raw or "")
    text = re.sub(r"<[^>]+>", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    if len(text) > max_len:
        return text[: max_len - 1].rstrip() + "…"
    return text


def parse_date(raw: str) -> datetime:
    try:
        dt = date_parser.parse(raw)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)
    except Exception:
        return utc_now()


def normalize_source_name(raw: str) -> str:
    s = (raw or "").strip().lower()
    if "reuters" in s:
        return "Reuters"
    if "associated press" in s or "ap news" in s or s == "ap":
        return "AP News"
    if "bloomberg" in s:
        return "Bloomberg"
    if "financial times" in s or s == "ft":
        return "Financial Times"
    if "wall street journal" in s or "wsj" in s:
        return "The Wall Street Journal"
    if "bbc" in s:
        return "BBC"
    if "cnbc" in s:
        return "CNBC"
    if "new york times" in s or "nytimes" in s:
        return "The New York Times"
    if "economist" in s:
        return "The Economist"
    if "iaea" in s:
        return "IAEA"
    if "world nuclear news" in s:
        return "World Nuclear News"
    if "nuclear engineering international" in s or "nei" == s:
        return "Nuclear Engineering International"
    if "power magazine" in s or "powermag" in s:
        return "POWER Magazine"
    return raw.strip() if raw else "Unknown"


def source_score(source: str) -> int:
    return TRUSTED_SOURCES.get(normalize_source_name(source), 0)


def is_noise(text: str) -> bool:
    lowered = text.lower()
    return any(pattern in lowered for pattern in BLOCKLIST_PATTERNS)


def load_config() -> Dict[str, object]:
    load_dotenv()
    cfg: Dict[str, object] = {
        "slack_bot_token": os.getenv("SLACK_BOT_TOKEN", ""),
        "slack_channel_id": os.getenv("SLACK_CHANNEL_ID", ""),
        "news_api_key": os.getenv("NEWS_API_KEY", ""),
        "ollama_base_url": os.getenv("OLLAMA_BASE_URL", "http://localhost:11434"),
        "gemma_model": os.getenv("GEMMA_MODEL", "gemma4:31b"),
        "max_articles": int(os.getenv("MAX_ARTICLES", "5")),
        "lookback_hours": int(os.getenv("LOOKBACK_HOURS", "30")),
        "ollama_timeout_seconds": int(os.getenv("OLLAMA_TIMEOUT_SECONDS", "300")),
    }

    required = ["slack_bot_token", "slack_channel_id"]
    missing = [k for k in required if not cfg[k]]
    if missing:
        raise RuntimeError(f"Missing required environment variables: {', '.join(missing)}")
    return cfg


def fetch_from_newsapi(news_api_key: str, lookback_hours: int) -> List[Article]:
    if not news_api_key:
        return []

    from_dt = (utc_now() - timedelta(hours=lookback_hours)).strftime("%Y-%m-%dT%H:%M:%SZ")
    params = {
        "q": "nuclear OR reactor OR SMR OR IAEA",
        "language": "en",
        "sortBy": "publishedAt",
        "from": from_dt,
        "pageSize": 50,
        "domains": ",".join(TRUSTED_DOMAINS),
        "apiKey": news_api_key,
    }

    try:
        resp = requests.get("https://newsapi.org/v2/everything", params=params, timeout=25)
        resp.raise_for_status()
        data = resp.json()
    except requests.RequestException:
        return []

    items: List[Article] = []
    for row in data.get("articles", []):
        title = clean_text(row.get("title", ""), 180)
        url = (row.get("url") or "").strip()
        source = normalize_source_name((row.get("source") or {}).get("name", "Unknown"))
        snippet = clean_text(row.get("description") or "", 350)
        published = parse_date(row.get("publishedAt", ""))

        if not title or not url or source_score(source) <= 0:
            continue
        if is_noise(f"{title} {snippet} {url}"):
            continue

        items.append(Article(title=title, url=url, source=source, published_at=published, snippet=snippet))

    return items


def fetch_from_google_rss(lookback_hours: int) -> List[Article]:
    oldest = utc_now() - timedelta(hours=lookback_hours)
    items: List[Article] = []

    for q in RSS_QUERIES:
        feed_url = f"https://news.google.com/rss/search?q={requests.utils.quote(q)}&hl=en-US&gl=US&ceid=US:en"
        feed = feedparser.parse(feed_url)

        for entry in feed.entries:
            title = clean_text(entry.get("title", ""), 180)
            link = (entry.get("link") or "").strip()
            source_raw = "Google News"
            if isinstance(entry.get("source"), dict):
                source_raw = entry.get("source", {}).get("title", "Google News")
            source = normalize_source_name(source_raw)
            snippet = clean_text(entry.get("summary", ""), 350)
            published = parse_date(entry.get("published", ""))

            if not title or not link or published < oldest:
                continue
            if source_score(source) <= 0:
                continue
            if is_noise(f"{title} {snippet} {link}"):
                continue

            items.append(Article(title=title, url=link, source=source, published_at=published, snippet=snippet))

    return items


def dedupe_articles(articles: List[Article]) -> List[Article]:
    seen = set()
    out: List[Article] = []

    for article in sorted(articles, key=lambda x: x.published_at, reverse=True):
        key = f"{article.source.lower()}::{article.title.lower()}"
        if key in seen:
            continue
        seen.add(key)
        out.append(article)

    return out


def rank_articles(articles: List[Article]) -> List[Article]:
    def score(article: Article) -> float:
        age_hours = max((utc_now() - article.published_at).total_seconds() / 3600.0, 0.0)
        recency = max(0.0, 36.0 - min(age_hours, 36.0)) / 36.0
        return source_score(article.source) + recency

    return sorted(articles, key=score, reverse=True)


def extract_json_object(text: str) -> Optional[Dict]:
    cleaned = (text or "").strip()
    if not cleaned:
        return None

    if cleaned.startswith("```"):
        lines = cleaned.splitlines()
        if lines and lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].startswith("```"):
            lines = lines[:-1]
        cleaned = "\n".join(lines).strip()

    if cleaned.lower().startswith("json"):
        cleaned = cleaned[4:].strip()

    start = cleaned.find("{")
    end = cleaned.rfind("}")
    if start != -1 and end != -1 and start < end:
        cleaned = cleaned[start : end + 1]

    try:
        parsed = json.loads(cleaned)
        if isinstance(parsed, dict):
            return parsed
    except json.JSONDecodeError:
        return None
    return None


def call_ollama_json(base_url: str, model: str, prompt: str, timeout_seconds: int) -> Optional[Dict]:
    body = {
        "model": model,
        "stream": False,
        "format": "json",
        "messages": [
            {"role": "system", "content": "당신은 원자력 뉴스를 한국어로 간결하게 요약하는 분석가이다."},
            {"role": "user", "content": prompt},
        ],
        "options": {"temperature": 0.2},
    }

    try:
        resp = requests.post(f"{base_url.rstrip('/')}/api/chat", json=body, timeout=timeout_seconds)
        resp.raise_for_status()
        content = (resp.json().get("message") or {}).get("content", "")
        return extract_json_object(content)
    except requests.RequestException:
        return None


def fallback_article_summary(article: Article) -> Dict[str, object]:
    one_line = clean_text(article.snippet, 120) if article.snippet else "원문 링크에서 세부 내용을 확인해 주세요."
    key_points = [clean_text(article.snippet, 90)] if article.snippet else ["핵심 내용을 자동 추출하지 못했습니다."]
    return {
        "title": article.title,
        "source": article.source,
        "url": article.url,
        "one_line_summary": one_line,
        "key_points": key_points[:3],
    }


def summarize_article(cfg: Dict[str, object], article: Article) -> Dict[str, object]:
    prompt = f"""
아래 기사 정보를 바탕으로 JSON만 반환하세요.
스키마:
{{
  "one_line_summary": "한국어 한 문장",
  "key_points": ["핵심내용1", "핵심내용2", "핵심내용3"]
}}

규칙:
- 과장 금지, 기사 정보 밖 추정 금지
- one_line_summary는 정확히 한 문장
- key_points는 최대 3개, 짧은 문장

기사:
- 제목: {article.title}
- 출처: {article.source}
- 내용: {article.snippet}
- 링크: {article.url}
""".strip()

    parsed = call_ollama_json(
        base_url=str(cfg["ollama_base_url"]),
        model=str(cfg["gemma_model"]),
        prompt=prompt,
        timeout_seconds=int(cfg["ollama_timeout_seconds"]),
    )
    if not parsed:
        return fallback_article_summary(article)

    one_line = clean_text(str(parsed.get("one_line_summary", "")), 140)
    key_points_raw = parsed.get("key_points", [])
    if isinstance(key_points_raw, list):
        key_points = [clean_text(str(x), 90) for x in key_points_raw if str(x).strip()][:3]
    else:
        key_points = []

    if not one_line:
        return fallback_article_summary(article)
    if not key_points:
        key_points = ["핵심내용 자동추출이 불완전해 원문 확인을 권장합니다."]

    return {
        "title": article.title,
        "source": article.source,
        "url": article.url,
        "one_line_summary": one_line,
        "key_points": key_points[:3],
    }


def summarize_trends(cfg: Dict[str, object], summarized_items: List[Dict[str, object]]) -> List[str]:
    compact = [
        {
            "title": item.get("title", ""),
            "source": item.get("source", ""),
            "one_line_summary": item.get("one_line_summary", ""),
        }
        for item in summarized_items
    ]

    prompt = f"""
아래 기사 요약들을 보고 오늘의 원자력 동향을 한국어 bullet 2~3개로 정리해.
JSON만 반환:
{{"trend_summary": ["bullet1", "bullet2", "bullet3"]}}
데이터:
{json.dumps(compact, ensure_ascii=False)}
""".strip()

    parsed = call_ollama_json(
        base_url=str(cfg["ollama_base_url"]),
        model=str(cfg["gemma_model"]),
        prompt=prompt,
        timeout_seconds=max(60, int(cfg["ollama_timeout_seconds"]) // 2),
    )

    if not parsed:
        return []

    raw = parsed.get("trend_summary", [])
    if isinstance(raw, list):
        return [clean_text(str(x), 120) for x in raw if str(x).strip()][:3]
    return []


def build_blocks(trends: List[str], items: List[Dict[str, object]]) -> List[Dict]:
    date_str = utc_now().strftime("%Y-%m-%d")
    blocks: List[Dict] = [
        {"type": "header", "text": {"type": "plain_text", "text": f"☢️ Daily Nuclear Brief | {date_str}"}},
        {
            "type": "context",
            "elements": [{"type": "mrkdwn", "text": "공신력 있는 글로벌 원자력 매체 중심 Top 5"}],
        },
        {"type": "divider"},
    ]

    if trends:
        trend_text = "*오늘의 동향 요약*\n" + "\n".join(f"• {t}" for t in trends)
        blocks.append({"type": "section", "text": {"type": "mrkdwn", "text": trend_text}})
        blocks.append({"type": "divider"})

    for idx, item in enumerate(items, start=1):
        title = clean_text(str(item.get("title", "제목 없음")), 140)
        source = clean_text(str(item.get("source", "Unknown")), 60)
        url = str(item.get("url", "")).strip()
        one_line = clean_text(str(item.get("one_line_summary", "요약 없음")), 160)
        key_points = item.get("key_points", [])
        if not isinstance(key_points, list):
            key_points = []
        key_points = [clean_text(str(x), 90) for x in key_points if str(x).strip()][:3]

        title_md = f"*{idx}. <{url}|{title}>*" if url else f"*{idx}. {title}*"
        detail = f"*한줄요약* {one_line}"
        if key_points:
            detail += "\n*핵심내용*\n" + "\n".join(f"• {kp}" for kp in key_points)

        blocks.extend(
            [
                {"type": "section", "text": {"type": "mrkdwn", "text": title_md}},
                {"type": "context", "elements": [{"type": "mrkdwn", "text": f"출처: *{source}*"}]},
                {"type": "section", "text": {"type": "mrkdwn", "text": detail}},
                {"type": "divider"},
            ]
        )

    return blocks


def build_fallback_text(items: List[Dict[str, object]], trends: List[str]) -> str:
    lines = [f"Daily Nuclear Brief ({utc_now().strftime('%Y-%m-%d')})"]
    if trends:
        lines.append("[오늘의 동향 요약]")
        lines.extend([f"- {t}" for t in trends])

    for i, item in enumerate(items, start=1):
        lines.append(f"{i}. {item.get('title', '제목 없음')}")
        lines.append(f"   출처: {item.get('source', 'Unknown')}")
        lines.append(f"   한줄요약: {item.get('one_line_summary', '요약 없음')}")
        for kp in item.get("key_points", [])[:3]:
            lines.append(f"   - {kp}")
        if item.get("url"):
            lines.append(f"   링크: {item.get('url')}")
    return "\n".join(lines)


def post_to_slack(token: str, channel: str, text: str, blocks: List[Dict]) -> None:
    client = WebClient(token=token)
    client.chat_postMessage(
        channel=channel,
        text=text,
        blocks=blocks,
        unfurl_links=False,
        unfurl_media=False,
    )


def run() -> None:
    cfg = load_config()

    collected = fetch_from_newsapi(str(cfg["news_api_key"]), int(cfg["lookback_hours"]))
    collected.extend(fetch_from_google_rss(int(cfg["lookback_hours"])))

    ranked = rank_articles(dedupe_articles(collected))
    top_articles = ranked[: max(5, int(cfg["max_articles"]) * 2)]

    if not top_articles:
        post_to_slack(
            token=str(cfg["slack_bot_token"]),
            channel=str(cfg["slack_channel_id"]),
            text="Daily Nuclear Brief\n조건에 맞는 공신력 원자력 기사를 찾지 못했습니다.",
            blocks=[],
        )
        return

    selected = top_articles[: int(cfg["max_articles"])]
    summarized = [summarize_article(cfg, article) for article in selected]
    trends = summarize_trends(cfg, summarized)

    fallback_text = build_fallback_text(summarized, trends)
    blocks = build_blocks(trends, summarized)

    post_to_slack(
        token=str(cfg["slack_bot_token"]),
        channel=str(cfg["slack_channel_id"]),
        text=fallback_text,
        blocks=blocks,
    )


if __name__ == "__main__":
    run()
