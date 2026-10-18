"""開早安日報頁面時，由本機即時抓取的社群與熱議資料

PTT、巴哈姆特等會擋 GitHub Actions 的 IP，所以不放在雲端日報，改在本機開頁面時抓，
結果快取 30 分鐘（social_cache.json，不進 git）。任何一個來源失敗都只是少一塊，不影響其他。

來源：PTT、巴哈姆特、Google 新聞頭條、LINE TODAY 排行。
不抓的來源：Dcard、Mobile01（擋抓取）、YouTube 熱門榜（沒有內容）、Reddit（限流）、
Threads／IG／FB（沒有公開資料）。
"""
import json
import re
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from xml.etree import ElementTree as ET

import requests

CACHE = Path(__file__).parent / "social_cache.json"
TTL = 30 * 60
UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/124 Safari/537.36",
      "Accept-Language": "zh-TW"}
TIMEOUT = 15

# 看板分組：(主題, [(看板代號, 顯示名稱)])
PTT_GROUPS = [
    ("時事與政治", [("Gossiping", "八卦"), ("HatePolitics", "政黑")]),
    ("財經與消費", [("Stock", "股票"), ("home-sale", "房屋買賣"), ("Lifeismoney", "省錢"), ("e-shopping", "網路購物")]),
    ("生活與感情", [("WomenTalk", "女性"), ("Boy-Girl", "男女"), ("movie", "電影")]),
    ("科技與工作", [("Tech_Job", "科技業"), ("MobileComm", "手機"), ("car", "汽車")]),
]


def _ptt_hot(board: str, pages: int = 2, top: int = 3, min_push: int = 8) -> list[list]:
    url = f"https://www.ptt.cc/bbs/{board}/index.html"
    posts = []
    for _ in range(pages):
        try:
            html = requests.get(url, headers=UA, cookies={"over18": "1"}, timeout=TIMEOUT).text
        except Exception:
            break
        for m in re.finditer(r'<div class="nrec">(?:<span[^>]*>([^<]*)</span>)?</div>\s*<div class="title">\s*(?:<a [^>]*>([^<]*)</a>)?', html):
            nrec, title = (m.group(1) or "").strip(), (m.group(2) or "").strip()
            if not title or "[公告]" in title or "本文已被刪除" in title:
                continue
            push = 100 if nrec == "爆" else int(nrec) if nrec.isdigit() else 0
            posts.append([title, push, nrec or "0"])
        prev = re.search(r'href="(/bbs/%s/index\d+\.html)">(?:‹|&lsaquo;) 上頁' % re.escape(board), html)
        if not prev:
            break
        url = "https://www.ptt.cc" + prev.group(1)
    posts.sort(key=lambda x: x[1], reverse=True)
    return [[t, n] for t, p, n in posts if p >= min_push][:top]


def _bahamut(top: int = 6) -> list[list]:
    try:
        data = requests.get("https://forum.gamer.com.tw/ajax/rank.php?c=21", headers=UA, timeout=TIMEOUT).json()
    except Exception:
        return []
    rows = [[d.get("msg", "").strip(), d.get("title", "").strip(), int(d.get("hot") or 0)] for d in data if d.get("msg")]
    rows.sort(key=lambda r: r[2], reverse=True)
    return rows[:top]


def _gnews(top: int = 12) -> list[list]:
    """Google 新聞台灣頭條。只取標題與來源，不取連結。"""
    try:
        root = ET.fromstring(requests.get("https://news.google.com/rss?hl=zh-TW&gl=TW&ceid=TW:zh-Hant", headers=UA, timeout=TIMEOUT).content)
    except Exception:
        return []
    out = []
    for item in root.iter("item"):
        t = (item.findtext("title") or "").strip()
        if not t:
            continue
        title, _, src = t.rpartition(" - ")
        out.append([title or t, src if title else ""])
        if len(out) >= top:
            break
    return out


def _line_today(top: int = 10) -> list[list]:
    """LINE TODAY 排行榜標題（頁面內嵌 JSON）。只取標題，不取連結。"""
    try:
        r = requests.get("https://today.line.me/tw/v2/ranking", headers=UA, timeout=TIMEOUT)
        r.encoding = "utf-8"
    except Exception:
        return []
    out, seen = [], set()
    for t in re.findall(r'"title":"(.*?)"', r.text):
        try:
            t = json.loads(f'"{t}"')
        except ValueError:
            continue
        if len(t) < 12 or t in seen:  # 太短的是分類名稱
            continue
        seen.add(t)
        out.append([t, "LINE TODAY"])
        if len(out) >= top:
            break
    return out


def fetch_all(force: bool = False) -> dict:
    if not force:
        try:
            c = json.loads(CACHE.read_text(encoding="utf-8"))
            if time.time() - c.get("ts", 0) < TTL:
                return c
        except Exception:
            pass
    boards = [b for _, bs in PTT_GROUPS for b, _ in bs]
    with ThreadPoolExecutor(max_workers=16) as ex:
        ptt_f = {b: ex.submit(_ptt_hot, b, 2, 3, 6 if b == "Gossiping" else 8) for b in boards}
        baha_f, news_f, line_f = ex.submit(_bahamut), ex.submit(_gnews), ex.submit(_line_today)
    data = {
        "ts": time.time(),
        "asof": time.strftime("%H:%M"),
        "ptt": {b: f.result() for b, f in ptt_f.items()},
        "bahamut": baha_f.result(),
        "gnews": news_f.result(),
        "line": line_f.result(),
    }
    if any(data["ptt"].values()) or data["bahamut"] or data["gnews"] or data["line"]:
        try:
            CACHE.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
        except Exception:
            pass
    return data


if __name__ == "__main__":
    d = fetch_all(force=True)
    print("Google 新聞頭條:", len(d["gnews"]), "| LINE TODAY:", len(d["line"]), "| 巴哈:", len(d["bahamut"]), "| PTT 看板有結果:", sum(1 for v in d["ptt"].values() if v), "/", len(d["ptt"]))
    for b, v in d["ptt"].items():
        print(b, v[:2])
