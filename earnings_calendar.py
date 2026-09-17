"""財報與法說會日期警示 — 避免在高不確定性時期進行當沖"""
import json
import os
import yfinance as yf
from datetime import date, datetime, timedelta
from net_timeout import call_with_timeout

# 快取 — get_daytrade_candidates() 對整份 WATCHLIST（150+ 檔）每天都會呼叫
# get_earnings_date()，若不快取等於每天對每一檔都補一次即時 yfinance 呼叫，
# 是拖垮單次 scan job（75分鐘上限）最主要的來源，比 fundamental_filter.py
# 原本就有快取的基本面查詢耗時多更多。快取邏輯與 fundamental_filter.py 一致。
CACHE_FILE     = os.path.join(os.path.dirname(__file__), "earnings_cache.json")
CACHE_TTL_DAYS = 7


def _load_cache() -> dict:
    if not os.path.exists(CACHE_FILE):
        return {}
    try:
        with open(CACHE_FILE, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def _save_cache(data: dict):
    try:
        with open(CACHE_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
    except Exception:
        pass


def _is_fresh(fetched_date: str) -> bool:
    try:
        delta = (datetime.now() - datetime.strptime(fetched_date, "%Y-%m-%d")).days
        return delta < CACHE_TTL_DAYS
    except Exception:
        return False


def get_earnings_date(ticker: str) -> date | None:
    """用 yfinance 取得最近一次財報公布日（台股效果有限，美股較準），7天快取"""
    cache  = _load_cache()
    cached = cache.get(ticker, {})
    if cached and _is_fresh(cached.get("fetched_date", "")):
        return date.fromisoformat(cached["earnings_date"]) if cached.get("earnings_date") else None

    today = datetime.now().strftime("%Y-%m-%d")
    result: date | None = None
    try:
        cal = call_with_timeout(lambda: yf.Ticker(ticker).calendar, timeout=45, default=None)
        if cal is not None and not cal.empty:
            col = cal.columns[0] if hasattr(cal, "columns") else None
            if col is not None:
                val = cal.loc["Earnings Date", col] if "Earnings Date" in cal.index else None
                if val is not None:
                    result = val.date() if hasattr(val, "date") else None
    except Exception:
        result = None

    cache[ticker] = {"fetched_date": today, "earnings_date": result.isoformat() if result else None}
    _save_cache(cache)
    return result


def build_earnings_alert(holdings: dict, watchlist: dict, days_ahead: int = 5) -> str | None:
    """
    掃描持股中 N 天內有財報公布的標的
    回傳推播訊息；無則回傳 None
    """
    today    = date.today()
    deadline = today + timedelta(days=days_ahead)
    alerts   = []

    for name in holdings:
        ticker = watchlist.get(name)
        if not ticker:
            continue
        ed = get_earnings_date(ticker)
        if ed and today <= ed <= deadline:
            days_left = (ed - today).days
            alerts.append(f"• {name}｜財報 {ed.strftime('%m/%d')}（{days_left}天後）⚠️ 建議避免當沖")

    if not alerts:
        return None
    return "📋 【財報警示】以下持股近期公布財報，請降低操作頻率\n" + "\n".join(alerts)


def has_earnings_risk(name: str, ticker: str, days_ahead: int = 3) -> bool:
    """當沖候選是否在財報前 N 天內（是則降低推播優先度）"""
    today = date.today()
    ed    = get_earnings_date(ticker)
    return ed is not None and today <= ed <= today + timedelta(days=days_ahead)
