"""社群趨勢 + 行銷日曆模組"""
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta

import requests

_TIMEOUT = 10


def _fetch_google_trends_tw() -> list[str]:
    url = "https://trends.google.com.tw/trending/rss?geo=TW"
    try:
        resp = requests.get(url, timeout=_TIMEOUT, headers={
            "User-Agent": "Mozilla/5.0"
        })
        resp.encoding = "utf-8"
        root = ET.fromstring(resp.text)
        titles = []
        for item in root.iter("item"):
            title = item.findtext("title", "").strip()
            if title:
                titles.append(title)
        return titles[:8]
    except Exception as e:
        print(f"[趨勢] Google Trends 抓取失敗：{e}")
        return []


_MARKETING_CALENDAR = {
    (1, 1): "元旦",
    (2, 14): "情人節",
    (3, 8): "婦女節",
    (3, 14): "白色情人節",
    (4, 4): "兒童節",
    (4, 22): "世界地球日",
    (5, 1): "勞動節",
    (6, 18): "端午節（約）",
    (7, 7): "七夕（約）",
    (8, 8): "父親節",
    (8, 26): "國際愛狗日",
    (9, 1): "開學季",
    (9, 28): "教師節",
    (10, 4): "世界動物日",
    (10, 31): "萬聖節",
    (11, 11): "雙11購物節",
    (12, 22): "冬至（約）",
    (12, 24): "平安夜",
    (12, 25): "聖誕節",
    (12, 31): "跨年",
}

_PET_DATES = {
    (2, 22): "貓之日",
    (3, 23): "世界幼犬日",
    (4, 11): "國際寵物日",
    (4, 25): "世界導盲犬日",
    (5, 8): "世界流浪動物日",
    (6, 4): "擁抱貓日",
    (8, 8): "世界貓咪日",
    (8, 26): "國際愛狗日",
    (10, 1): "世界素食日（寵物友善飲食）",
    (10, 4): "世界動物日",
    (10, 29): "世界貓咪日",
    (11, 1): "世界純素日",
    (12, 2): "全國狗展月",
}


def _get_upcoming_events(days_ahead: int = 7) -> list[dict]:
    today = datetime.now().date()
    events = []
    for d in range(days_ahead + 1):
        check = today + timedelta(days=d)
        key = (check.month, check.day)

        for cal, cal_type in [(_MARKETING_CALENDAR, "行銷"), (_PET_DATES, "寵物")]:
            if key in cal:
                events.append({
                    "date": check.strftime("%m/%d"),
                    "name": cal[key],
                    "type": cal_type,
                    "days": d,
                })
    return events


def fetch_social_trends() -> dict:
    trends = _fetch_google_trends_tw()
    events = _get_upcoming_events(7)
    return {"trends": trends, "events": events}


def format_social_trends(data: dict) -> str:
    lines = []

    trends = data.get("trends", [])
    if trends:
        lines.append("📱 台灣熱搜趨勢")
        for i, t in enumerate(trends[:5], 1):
            lines.append(f"  {i}. {t}")

    events = data.get("events", [])
    if events:
        lines.append("\n📅 近期行銷節點")
        for e in events:
            tag = "🐾" if e["type"] == "寵物" else "📌"
            if e["days"] == 0:
                lines.append(f"  {tag} 今天！{e['name']}")
            else:
                lines.append(f"  {tag} {e['date']} {e['name']}（{e['days']}天後）")

    pet_events = [e for e in events if e["type"] == "寵物"]
    if pet_events:
        lines.append("\n💡 寵物行銷建議")
        for e in pet_events[:2]:
            lines.append(f"  → {e['name']}可規劃主題活動/社群貼文")

    return "\n".join(lines) if lines else ""
