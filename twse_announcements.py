"""從 TWSE 抓持股的重大公告，有新公告時回傳提醒訊息"""
import urllib.request
import json
from datetime import datetime, timedelta


_KEYWORDS = ["減資", "現金增資", "合併", "下市", "停止買賣", "重大訊息", "財務報告", "法說會", "董事會決議"]


def fetch_announcements(stock_code: str, days_back: int = 2) -> list[dict]:
    """抓指定台股代號最近 N 天的重大訊息公告"""
    code = stock_code.replace(".TW", "").replace(".TWO", "")
    if "." in code:
        return []
    results = []
    for i in range(days_back):
        date = (datetime.now() - timedelta(days=i)).strftime("%Y%m%d")
        url  = (f"https://www.twse.com.tw/rwd/zh/announcement/announcement"
                f"?date={date}&stockNo={code}&response=json")
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
            with urllib.request.urlopen(req, timeout=8) as resp:
                data = json.loads(resp.read())
            for row in data.get("data", []):
                title = row[2] if len(row) > 2 else ""
                if any(kw in title for kw in _KEYWORDS):
                    results.append({"date": date, "code": code, "title": title})
        except Exception:
            continue
    return results


def build_announcement_alert(holdings: dict, watchlist: dict) -> str | None:
    """掃描所有持股的重大公告，有結果就回傳推播訊息"""
    alerts = []
    for name in holdings:
        ticker = watchlist.get(name, "")
        if not ticker.endswith(".TW"):
            continue
        rows = fetch_announcements(ticker, days_back=2)
        for r in rows:
            alerts.append(f"• {name}（{r['code']}）\n  {r['title']}（{r['date']}）")
    if not alerts:
        return None
    return "📢 【持股重大公告】\n" + "\n".join(alerts)
