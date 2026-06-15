"""
月營收趨勢分析 — 從公開資訊觀測站（MOPS）抓取台股月營收
每月 10 日後公告，快取 30 天避免重複抓取

回傳指標：
  - revenue_yoy:  月營收年增率（YoY %）— 最重要，去除季節性
  - revenue_mom:  月營收月增率（MoM %）
  - consecutive_growth: 連續成長月數（正=連續YoY正成長）
  - trend_signal: "strong_growth" / "growth" / "decline" / "strong_decline" / "neutral"
"""
import json
import urllib.request
import urllib.parse
from datetime import datetime, timedelta
from pathlib import Path

CACHE_FILE = Path(__file__).parent / "revenue_cache.json"
CACHE_TTL_DAYS = 30


def _load_cache() -> dict:
    try:
        return json.loads(CACHE_FILE.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _save_cache(data: dict):
    try:
        CACHE_FILE.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception:
        pass


def _is_fresh(fetched_date: str) -> bool:
    try:
        delta = (datetime.now() - datetime.strptime(fetched_date, "%Y-%m-%d")).days
        return delta < CACHE_TTL_DAYS
    except Exception:
        return False


def _tw_year_month(offset_months: int = 0) -> tuple[int, int]:
    """回傳台灣民國年 + 月（offset_months=負數往前推）"""
    now = datetime.now()
    total = now.year * 12 + (now.month - 1) + offset_months
    year  = total // 12
    month = total % 12 + 1
    tw_year = year - 1911
    return tw_year, month


def _fetch_mops(stock_code: str, tw_year: int, month: int) -> int | None:
    """抓指定月份月營收（單位：千元）"""
    url = "https://mops.twse.com.tw/nas/t21/sii/t21sc03_{tw_year}_{month}_0.html".format(
        tw_year=tw_year, month=month
    )
    try:
        req = urllib.request.Request(url, headers={
            "User-Agent": "Mozilla/5.0",
            "Accept-Encoding": "identity",
        })
        with urllib.request.urlopen(req, timeout=12) as resp:
            html = resp.read().decode("big5", errors="replace")
    except Exception:
        # 上市公司找不到時試上櫃
        try:
            url2 = "https://mops.twse.com.tw/nas/t21/otc/t21sc03_{tw_year}_{month}_0.html".format(
                tw_year=tw_year, month=month
            )
            req2 = urllib.request.Request(url2, headers={
                "User-Agent": "Mozilla/5.0",
                "Accept-Encoding": "identity",
            })
            with urllib.request.urlopen(req2, timeout=12) as resp2:
                html = resp2.read().decode("big5", errors="replace")
        except Exception:
            return None

    # 逐行掃描找目標代號
    import re
    # 找含股票代號的 <tr>
    rows = re.findall(r'<tr[^>]*>(.*?)</tr>', html, re.DOTALL | re.IGNORECASE)
    for row in rows:
        cells = re.findall(r'<td[^>]*>(.*?)</td>', row, re.DOTALL | re.IGNORECASE)
        cleaned = [re.sub(r'<[^>]+>', '', c).strip().replace(',', '').replace('\xa0', '') for c in cells]
        if not cleaned:
            continue
        if cleaned[0] == stock_code:
            # 欄位：代號, 公司, 當月, 上月, 去年同月, YoY%, MoM%, 累計今年, 累計去年, YoY累計%
            try:
                return int(cleaned[2]) if cleaned[2].lstrip('-').isdigit() else None
            except Exception:
                return None
    return None


def fetch_revenue_trend(stock_code: str, months: int = 6) -> dict:
    """
    抓最近 N 個月營收，計算 YoY / MoM 及趨勢
    回傳 dict 或 {}（失敗時）
    """
    code = stock_code.replace(".TW", "").replace(".TWO", "")
    if "." in code or not code.isdigit():
        return {}

    cache     = _load_cache()
    cache_key = f"{code}_trend"
    cached    = cache.get(cache_key, {})
    if cached and _is_fresh(cached.get("fetched_date", "")):
        return cached

    # 抓近 months+12 個月資料（YoY 需要去年同月）
    revenue_map: dict[str, int] = {}
    now = datetime.now()
    for offset in range(-(months + 12), 1):
        tw_year, month = _tw_year_month(offset)
        key = f"{tw_year:03d}{month:02d}"
        if key in revenue_map:
            continue
        val = _fetch_mops(code, tw_year, month)
        if val is not None and val > 0:
            revenue_map[key] = val

    if len(revenue_map) < 2:
        return {}

    sorted_keys = sorted(revenue_map.keys(), reverse=True)

    # 計算 YoY / MoM
    records = []
    for key in sorted_keys[:months]:
        tw_y  = int(key[:3])
        mon   = int(key[3:])
        rev   = revenue_map[key]
        # 去年同月
        prev_y_key = f"{tw_y - 1:03d}{mon:02d}"
        yoy = None
        if prev_y_key in revenue_map and revenue_map[prev_y_key] > 0:
            yoy = round((rev - revenue_map[prev_y_key]) / revenue_map[prev_y_key] * 100, 1)
        # 上個月
        prev_m_tw, prev_m_mon = _tw_year_month((tw_y + 1911) * 12 + (mon - 1) - now.year * 12 - now.month)
        prev_m_key = f"{prev_m_tw:03d}{prev_m_mon:02d}"
        mom = None
        if prev_m_key in revenue_map and revenue_map[prev_m_key] > 0:
            mom = round((rev - revenue_map[prev_m_key]) / revenue_map[prev_m_key] * 100, 1)
        records.append({"period": f"{tw_y+1911}/{mon:02d}", "revenue": rev, "yoy": yoy, "mom": mom})

    if not records:
        return {}

    latest = records[0]
    yoy    = latest.get("yoy")
    mom    = latest.get("mom")

    # 連續成長月數（連續 YoY > 0）
    consecutive = 0
    for r in records:
        if r["yoy"] is not None:
            if r["yoy"] > 0:
                consecutive += 1
            else:
                break

    # 趨勢訊號
    if yoy is not None:
        if yoy >= 20 and consecutive >= 3:
            trend = "strong_growth"
        elif yoy > 0 and consecutive >= 2:
            trend = "growth"
        elif yoy <= -20:
            trend = "strong_decline"
        elif yoy < 0:
            trend = "decline"
        else:
            trend = "neutral"
    else:
        trend = "unknown"

    result = {
        "fetched_date":       datetime.now().strftime("%Y-%m-%d"),
        "latest_period":      latest["period"],
        "latest_revenue":     latest["revenue"],
        "revenue_yoy":        yoy,
        "revenue_mom":        mom,
        "consecutive_growth": consecutive,
        "trend_signal":       trend,
        "history":            records[:6],
    }
    cache[cache_key] = result
    _save_cache(cache)
    return result


def get_revenue_signal(stock_code: str) -> dict:
    """
    回傳評分用訊號
    {
      "score_delta": int,      # 對總分的加/減分
      "label": str,            # 顯示用文字
      "trend": str,
    }
    """
    data = fetch_revenue_trend(stock_code)
    if not data or data.get("trend_signal") == "unknown":
        return {"score_delta": 0, "label": "", "trend": "unknown"}

    trend = data["trend_signal"]
    yoy   = data.get("revenue_yoy")
    cons  = data.get("consecutive_growth", 0)
    period = data.get("latest_period", "")

    score_delta = 0
    if trend == "strong_growth":
        score_delta = 10
        label = f"📈 月營收 YoY +{yoy:.0f}%（連{cons}月成長）[{period}]"
    elif trend == "growth":
        score_delta = 5
        label = f"📊 月營收 YoY +{yoy:.0f}%（{period}）"
    elif trend == "strong_decline":
        score_delta = -10
        label = f"📉 月營收 YoY {yoy:.0f}%，持續衰退 [{period}]"
    elif trend == "decline":
        score_delta = -5
        label = f"⚠️ 月營收 YoY {yoy:.0f}%（{period}）"
    else:
        label = f"月營收 YoY {yoy:.0f}%（持平）[{period}]" if yoy is not None else ""

    return {"score_delta": score_delta, "label": label, "trend": trend}
