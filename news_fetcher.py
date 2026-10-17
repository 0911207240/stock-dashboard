"""每日新聞抓取模組 — 升級版：財經、台股重大訊息、時事、AI趨勢、行銷電商、寵物產業"""

import xml.etree.ElementTree as ET
import requests

_TIMEOUT = 10
_MAX_PER_CATEGORY = 3  # 每類只取前3條，控制總字數

_RSS_SOURCES = {
    "台股重大訊息": [
        ("https://openapi.twse.com.tw/v1/opendata/t187ap04_L", "twse_json"),
    ],
    "財經市場": [
        ("https://news.cnyes.com/api/v3/news/category/headline?limit=10", "cnyes_api"),
        ("https://www.moneydj.com/FUNDDJ/YaPages/YaRSSNewsContent.aspx?svc=NB", "rss"),
    ],
    "台灣時事": [
        ("https://feeds.feedburner.com/rsscna/social", "rss"),
        ("https://news.ltn.com.tw/rss/all.xml", "rss"),
    ],
    "政治": [
        ("https://feeds.feedburner.com/rsscna/politics", "rss"),
        ("https://news.google.com/rss/search?q=立法院+行政院+中央社&hl=zh-TW&gl=TW&ceid=TW:zh-Hant", "rss"),
    ],
    "房地產": [
        ("https://news.google.com/rss/search?q=房地產+房市+台灣&hl=zh-TW&gl=TW&ceid=TW:zh-Hant", "rss"),
    ],
    "AI趨勢": [
        ("https://technews.tw/feed/", "rss"),
        ("https://news.google.com/rss/search?q=AI+人工智慧+台灣&hl=zh-TW&gl=TW&ceid=TW:zh-Hant", "rss"),
    ],
    "行銷電商": [
        ("https://news.google.com/rss/search?q=電商+跨境+行銷+台灣&hl=zh-TW&gl=TW&ceid=TW:zh-Hant", "rss"),
    ],
    "寵物產業": [
        ("https://news.google.com/rss/search?q=寵物+市場+台灣&hl=zh-TW&gl=TW&ceid=TW:zh-Hant", "rss"),
    ],
}

def _fetch_rss(url: str) -> list[dict]:
    try:
        resp = requests.get(url, timeout=_TIMEOUT, headers={"User-Agent": "Mozilla/5.0"})
        resp.encoding = "utf-8"
        root = ET.fromstring(resp.text)
        items = []
        for item in root.iter("item"):
            title = item.findtext("title", "").strip()
            link = item.findtext("link", "").strip()
            if title:
                title = title.split(" - ")[0].strip()
                items.append({"title": title, "link": link})
        return items[:_MAX_PER_CATEGORY]
    except Exception as e:
        print(f"[新聞] RSS 抓取失敗 {url}: {e}")
        return []

def _fetch_cnyes(url: str) -> list[dict]:
    try:
        resp = requests.get(url, timeout=_TIMEOUT, headers={"User-Agent": "Mozilla/5.0"})
        data = resp.json()
        items = []
        for article in data.get("items", {}).get("data", [])[:_MAX_PER_CATEGORY]:
            title = article.get("title", "").strip()
            news_id = article.get("newsId", "")
            link = f"https://news.cnyes.com/news/id/{news_id}" if news_id else ""
            if title:
                items.append({"title": title, "link": link})
        return items
    except Exception as e:
        print(f"[新聞] 鉅亨網抓取失敗：{e}")
        return []

_MATERIAL_KEYWORDS = ("股利", "庫藏股", "合併", "減資", "增資", "私募", "處分", "取得", "訴訟", "法說", "裁罰", "停工", "召開")


def _fetch_twse_material(url: str) -> list[dict]:
    """證交所上市公司重大訊息（開放資料）；只留含關鍵字者，避免例行公告洗版"""
    try:
        resp = requests.get(url, timeout=_TIMEOUT, headers={"User-Agent": "Mozilla/5.0"})
        resp.encoding = "utf-8"
        items = []
        for row in resp.json():
            subject = next((v for k, v in row.items() if k.startswith("主旨")), "")
            name = row.get("公司名稱", "")
            first = " ".join(str(subject).split())
            if name and first and any(k in first for k in _MATERIAL_KEYWORDS):
                items.append({"title": f"{name}：{first[:40]}", "link": ""})
            if len(items) >= _MAX_PER_CATEGORY:
                break
        return items
    except Exception as e:
        print(f"[新聞] 證交所重大訊息抓取失敗：{e}")
        return []


def fetch_daily_news() -> dict:
    result = {}
    for category, sources in _RSS_SOURCES.items():
        articles = []
        for url, source_type in sources:
            if source_type == "cnyes_api":
                articles.extend(_fetch_cnyes(url))
            elif source_type == "twse_json":
                articles.extend(_fetch_twse_material(url))
            else:
                articles.extend(_fetch_rss(url))
            if len(articles) >= _MAX_PER_CATEGORY:
                break
        result[category] = articles[:_MAX_PER_CATEGORY]
    return result

def format_daily_news(news: dict) -> str:
    if not news:
        return ""
    emoji_map = {
        "台股重大訊息": "🔔",
        "財經市場":     "💰",
        "台灣時事":     "🏛️",
        "政治":         "🗳️",
        "房地產":       "🏠",
        "AI趨勢":       "🤖",
        "行銷電商":     "🛒",
        "寵物產業":     "🐾",
    }
    order = ["台股重大訊息", "財經市場", "台灣時事", "政治", "房地產", "AI趨勢", "行銷電商", "寵物產業"]
    lines = ["📰 精選報導"]
    for category in order:
        articles = news.get(category, [])
        if not articles:
            continue
        emoji = emoji_map.get(category, "📌")
        lines.append(f"\n{emoji} {category}")
        for i, a in enumerate(articles[:3], 1):
            lines.append(f" {i}. {a['title']}")
    return "\n".join(lines) if len(lines) > 1 else ""
