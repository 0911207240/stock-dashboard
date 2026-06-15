"""
月營收趨勢分析 — 從公開資訊觀測站（MOPS）抓取台股月營收
每月 10 日後公告，快取策略：整月資料一次下載並快取（更穩定）

回傳指標：
  - revenue_yoy:  月營收年增率（YoY %）
  - revenue_mom:  月營收月增率（MoM %）
  - consecutive_growth: 連續YoY正成長月數
  - trend_signal: "strong_growth" / "growth" / "decline" / "strong_decline" / "neutral"
"""
import json
import re
import urllib.request
from datetime import datetime
from pathlib import Path

CACHE_FILE     = Path(__file__).parent / "revenue_cache.json"
CACHE_TTL_DAYS = 28   # 月營收每月更新一次，快取稍長


# ── 快取 ──────────────────────────────────────────────────

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


def _is_fresh(fetched_date: str, ttl_days: int = CACHE_TTL_DAYS) -> bool:
    try:
        return (datetime.now() - datetime.strptime(fetched_date, "%Y-%m-%d")).days < ttl_days
    except Exception:
        return False


# ── 民國年月工具 ───────────────────────────────────────────

def _prev_ym(tw_year: int, month: int) -> tuple[int, int]:
    """回傳前一個月的 (民國年, 月)"""
    if month > 1:
        return tw_year, month - 1
    return tw_year - 1, 12


def _ad_to_roc(ad_year: int, month: int) -> tuple[int, int]:
    return ad_year - 1911, month


def _recent_periods(count: int = 18) -> list[tuple[int, int]]:
    """回傳最近 count 個月的 (民國年, 月) 清單，由新到舊"""
    now = datetime.now()
    y, m = now.year - 1911, now.month
    result = []
    for _ in range(count):
        result.append((y, m))
        y, m = _prev_ym(y, m)
    return result


# ── MOPS 抓取（一次取整月、全市場）───────────────────────

def _fetch_month_all(tw_year: int, month: int) -> dict[str, int]:
    """
    抓 MOPS 指定年月的月營收 HTML，解析所有股票。
    回傳 {股票代號: 當月營收千元}
    先試上市(sii)，找不到資料再試上櫃(otc)。
    """
    result = {}
    for market in ("sii", "otc"):
        url = (
            f"https://mops.twse.com.tw/nas/t21/{market}/"
            f"t21sc03_{tw_year}_{month}_0.html"
        )
        try:
            req = urllib.request.Request(url, headers={
                "User-Agent": "Mozilla/5.0",
                "Accept-Encoding": "identity",
            })
            with urllib.request.urlopen(req, timeout=15) as resp:
                html = resp.read().decode("big5", errors="replace")
        except Exception:
            continue

        rows = re.findall(r'<tr[^>]*>(.*?)</tr>', html, re.DOTALL | re.IGNORECASE)
        for row in rows:
            cells = re.findall(r'<td[^>]*>(.*?)</td>', row, re.DOTALL | re.IGNORECASE)
            cleaned = [re.sub(r'<[^>]+>', '', c).strip().replace(',', '').replace('\xa0', '') for c in cells]
            if len(cleaned) < 3:
                continue
            code = cleaned[0]
            if not re.match(r'^\d{4,6}$', code):
                continue
            try:
                val = int(cleaned[2])
                if val > 0:
                    result[code] = val
            except (ValueError, IndexError):
                continue

    return result


def _get_month_data(tw_year: int, month: int, cache: dict) -> dict[str, int]:
    """
    從快取取整月資料，若過期才重新抓取。
    快取 key: "month_{year}_{month:02d}"
    """
    key = f"month_{tw_year}_{month:02d}"
    entry = cache.get(key, {})
    # 整月資料快取 28 天（下個月更新後才需重抓）
    if entry.get("fetched_date") and _is_fresh(entry["fetched_date"]):
        return entry.get("data", {})

    data = _fetch_month_all(tw_year, month)
    if data:
        cache[key] = {"fetched_date": datetime.now().strftime("%Y-%m-%d"), "data": data}
        _save_cache(cache)
    return data


# ── 公開 API ───────────────────────────────────────────────

def fetch_revenue_trend(stock_code: str, months: int = 6) -> dict:
    """
    抓最近 N 個月營收，計算 YoY / MoM 及趨勢。
    回傳 dict 或 {}（失敗或無資料時）
    """
    code = stock_code.replace(".TW", "").replace(".TWO", "")
    if not re.match(r'^\d{4,6}$', code):
        return {}

    cache     = _load_cache()
    cache_key = f"trend_{code}"
    cached    = cache.get(cache_key, {})
    if cached and _is_fresh(cached.get("fetched_date", ""), ttl_days=7):
        return cached

    # 取近 months+13 個月（YoY 需去年同月）
    periods = _recent_periods(months + 13)

    # 收集各月營收
    rev_map: dict[str, int] = {}   # key: "114_05" → 千元
    for tw_y, mon in periods:
        mkey = f"{tw_y}_{mon:02d}"
        if mkey in rev_map:
            continue
        month_data = _get_month_data(tw_y, mon, cache)
        if code in month_data:
            rev_map[mkey] = month_data[code]

    if len(rev_map) < 2:
        return {}

    # 排序：由新到舊
    sorted_keys = sorted(rev_map.keys(), reverse=True)

    records = []
    for mkey in sorted_keys[:months]:
        tw_y_str, mon_str = mkey.split("_")
        tw_y = int(tw_y_str)
        mon  = int(mon_str)
        rev  = rev_map[mkey]

        # YoY：去年同月
        prev_y_key = f"{tw_y - 1}_{mon:02d}"
        yoy = None
        if prev_y_key in rev_map and rev_map[prev_y_key] > 0:
            yoy = round((rev - rev_map[prev_y_key]) / rev_map[prev_y_key] * 100, 1)

        # MoM：上個月（修正版，使用 _prev_ym 避免計算錯誤）
        prev_tw_y, prev_mon = _prev_ym(tw_y, mon)
        prev_m_key = f"{prev_tw_y}_{prev_mon:02d}"
        mom = None
        if prev_m_key in rev_map and rev_map[prev_m_key] > 0:
            mom = round((rev - rev_map[prev_m_key]) / rev_map[prev_m_key] * 100, 1)

        records.append({
            "period":  f"{tw_y + 1911}/{mon:02d}",
            "revenue": rev,
            "yoy":     yoy,
            "mom":     mom,
        })

    if not records:
        return {}

    latest = records[0]
    yoy    = latest.get("yoy")
    mom    = latest.get("mom")

    # 連續 YoY 正成長月數
    consecutive = 0
    for r in records:
        if r["yoy"] is not None:
            if r["yoy"] > 0:
                consecutive += 1
            else:
                break

    # 趨勢判斷
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
    回傳評分用訊號：
    {
      "score_delta": int,
      "label": str,
      "trend": str,
      "yoy": float | None,
    }
    """
    data = fetch_revenue_trend(stock_code)
    if not data or data.get("trend_signal") == "unknown":
        return {"score_delta": 0, "label": "", "trend": "unknown", "yoy": None}

    trend  = data["trend_signal"]
    yoy    = data.get("revenue_yoy")
    cons   = data.get("consecutive_growth", 0)
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

    return {"score_delta": score_delta, "label": label, "trend": trend, "yoy": yoy}
