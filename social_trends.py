"""社群趨勢 + 行銷日曆模組"""
import re
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta

import requests

_TIMEOUT = 10


_FOREIGN = re.compile(r"[\u0E00-\u0E7F\u0600-\u06FF\u0400-\u04FF\u3040-\u30FF\uAC00-\uD7AF]|\bklasemen\b|\bvs\b", re.I)  # 泰文、阿拉伯文、西里爾、日韓文


def _fetch_google_trends_tw() -> list[str]:
    url = "https://trends.google.com.tw/trending/rss?geo=TW"
    try:
        resp = requests.get(url, timeout=_TIMEOUT, headers={
            "User-Agent": "Mozilla/5.0"
        })
        resp.encoding = "utf-8"
        root = ET.fromstring(resp.text)
        ns = {"ht": "https://trends.google.com/trending/rss"}
        titles = []
        for item in root.iter("item"):
            title = item.findtext("title", "").strip()
            traffic = item.findtext("ht:approx_traffic", "", ns).strip()
            if title:
                titles.append(f"{title}（搜尋量 {traffic}）" if traffic else title)
        return [t for t in titles if not _FOREIGN.search(t)][:10]
    except Exception as e:
        print(f"[趨勢] Google Trends 抓取失敗：{e}")
        return []


def _ptt_score(nrec: str) -> int:
    if nrec == "爆":
        return 100
    return int(nrec) if nrec.isdigit() else 0


def _fetch_ptt_hot(board: str = "Gossiping", pages: int = 2, top: int = 3, min_push: int = 10) -> list[dict]:
    """抓看板最近幾頁，回傳推文數最高的幾篇（只取標題與推文數，不放連結）"""
    url = f"https://www.ptt.cc/bbs/{board}/index.html"
    posts = []
    for _ in range(pages):
        try:
            html = requests.get(url, timeout=_TIMEOUT, headers={"User-Agent": "Mozilla/5.0"},
                                cookies={"over18": "1"}).text
        except Exception as e:
            print(f"[趨勢] PTT {board} 抓取失敗：{e}")
            break
        for m in re.finditer(r'<div class="nrec">(?:<span[^>]*>([^<]*)</span>)?</div>\s*<div class="title">\s*(?:<a [^>]*>([^<]*)</a>)?',
                             html):
            nrec, title = (m.group(1) or "").strip(), (m.group(2) or "").strip()
            if title and "[公告]" not in title:
                posts.append({"title": title, "push": _ptt_score(nrec), "label": nrec or "0"})
        prev = re.search(r'href="(/bbs/%s/index\d+\.html)">(?:‹|&lsaquo;) 上頁' % board, html)
        if not prev:
            break
        url = "https://www.ptt.cc" + prev.group(1)
    posts.sort(key=lambda x: x["push"], reverse=True)
    return [p for p in posts if p["push"] >= min_push][:top]


_MARKETING_CALENDAR = {
    (1, 1): "元旦｜新年新品上架",
    (1, 15): "年貨大街開跑｜春節送禮選物",
    (2, 14): "情人節｜送禮選物檔期",
    (3, 8): "婦女節｜女性選物主題",
    (3, 14): "白色情人節｜回禮選物",
    (4, 4): "兒童節｜親子選物",
    (4, 22): "世界地球日｜環保選物主題",
    (5, 1): "勞動節｜犒賞自己選物",
    (5, 11): "母親節｜送禮選物重點檔期",
    (6, 18): "端午節（約）｜節慶選物",
    (7, 7): "七夕｜浪漫選物檔期",
    (7, 15): "暑假購物季",
    (8, 8): "父親節｜送禮選物",
    (9, 1): "開學季｜生活選物",
    (9, 28): "教師節",
    (10, 31): "萬聖節｜主題選物",
    (11, 1): "雙11暖身｜預熱活動規劃",
    (11, 11): "雙11購物節｜AUNO 年度大促",
    (12, 12): "雙12購物節｜年末清倉",
    (12, 22): "冬至（約）",
    (12, 24): "平安夜｜聖誕交換禮物選物",
    (12, 25): "聖誕節｜節慶選物",
    (12, 31): "跨年｜年末感謝祭",
}

_AUNO_DATES = {
    (1, 20): "AUNO 春節特惠預告期",
    (3, 1): "AUNO 春季新品上架",
    (5, 5): "AUNO 母親節檔期開跑",
    (6, 1): "AUNO 年中慶規劃",
    (8, 1): "AUNO 父親節檔期開跑",
    (9, 15): "AUNO 秋季新品上架",
    (10, 25): "AUNO 雙11預熱規劃",
    (11, 25): "AUNO 聖誕檔期開跑",
}

_PET_DATES = {
    (2, 22): "貓之日",
    (3, 23): "世界幼犬日",
    (4, 11): "國際寵物日",
    (5, 8): "世界流浪動物日",
    (8, 8): "世界貓咪日",
    (8, 26): "國際愛狗日",
    (10, 4): "世界動物日",
}


def _get_upcoming_events(days_ahead: int = 7) -> list[dict]:
    today = datetime.now().date()
    events = []
    for d in range(days_ahead + 1):
        check = today + timedelta(days=d)
        key = (check.month, check.day)

        for cal, cal_type in [(_AUNO_DATES, "AUNO"), (_MARKETING_CALENDAR, "行銷"), (_PET_DATES, "寵物")]:
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
    ptt = _fetch_ptt_hot("Gossiping")
    return {"trends": trends, "events": events, "ptt": ptt}


def format_social_trends(data: dict) -> str:
    lines = []

    trends = data.get("trends", [])
    if trends:
        lines.append("📱 台灣熱搜趨勢")
        for i, t in enumerate(trends[:10], 1):
            lines.append(f"  {i}. {t}")

    ptt = data.get("ptt", [])
    if ptt:
        lines.append("\n💬 PTT 八卦板高推文")
        for i, p in enumerate(ptt, 1):
            lines.append(f"  {i}. {p['title']}（推 {p['label']}）")

    events = data.get("events", [])
    if events:
        lines.append("\n📅 近期行銷節點")
        for e in events:
            tag = {"AUNO": "🛍️", "寵物": "🐾", "行銷": "📌"}.get(e["type"], "📌")
            if e["days"] == 0:
                lines.append(f"  {tag} 今天！{e['name']}")
            else:
                lines.append(f"  {tag} {e['date']} {e['name']}（{e['days']}天後）")

    auno_events = [e for e in events if e["type"] == "AUNO"]
    if auno_events:
        lines.append("\n🛍️ AUNO 行動建議")
        for e in auno_events[:2]:
            lines.append(f"  → {e['name']}：準備素材/活動頁/社群預告")

    pet_events = [e for e in events if e["type"] == "寵物"]
    if pet_events:
        lines.append("\n🐾 寵物節日提醒")
        for e in pet_events[:2]:
            lines.append(f"  → {e['name']}可搭配寵物選物主題")

    return "\n".join(lines) if lines else ""
