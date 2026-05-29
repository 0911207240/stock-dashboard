"""
基本面簡易過濾 — 排除 EPS 虧損且營收/獲利持續惡化的股票
避免在體質差的標的上觸發技術假訊號（當沖用）
快取 7 天，避免每日重抓 API
"""
import json
import os
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor, as_completed
import yfinance as yf

CACHE_FILE    = os.path.join(os.path.dirname(__file__), "fundamental_cache.json")
CACHE_TTL_DAYS = 7

# 金融業代碼範圍（EPS 計算方式不同，不適用此過濾）
_FINANCE_CODE_RANGE = range(2800, 3000)


def _is_etf(ticker: str) -> bool:
    code = ticker.replace(".TW", "").replace(".TWO", "")
    return code.startswith("00") or (len(code) == 5 and code.startswith("0"))


def _is_finance(ticker: str) -> bool:
    code = ticker.replace(".TW", "").replace(".TWO", "")
    try:
        return int(code) in _FINANCE_CODE_RANGE
    except ValueError:
        return False


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


def fetch_fundamentals(ticker: str) -> dict:
    """抓取並快取單檔基本面（EPS、營收成長、獲利成長）"""
    cache = _load_cache()
    cached = cache.get(ticker, {})
    if cached and _is_fresh(cached.get("fetched_date", "")):
        return cached

    today = datetime.now().strftime("%Y-%m-%d")
    try:
        info = yf.Ticker(ticker).info
        data = {
            "fetched_date":    today,
            "trailing_eps":    info.get("trailingEps"),
            "revenue_growth":  info.get("revenueGrowth"),
            "earnings_growth": info.get("earningsGrowth"),
        }
    except Exception:
        data = {"fetched_date": today}

    cache[ticker] = data
    _save_cache(cache)
    return data


def prefetch_all(watchlist: dict, max_workers: int = 8):
    """批次預載所有股票基本面（快取過期時呼叫，平行抓取）"""
    cache = _load_cache()
    stale = [
        (name, ticker)
        for name, ticker in watchlist.items()
        if not _is_etf(ticker)
        and not _is_finance(ticker)
        and not _is_fresh(cache.get(ticker, {}).get("fetched_date", ""))
    ]
    if not stale:
        return

    today = datetime.now().strftime("%Y-%m-%d")

    def _fetch(ticker):
        try:
            info = yf.Ticker(ticker).info
            return ticker, {
                "fetched_date":    today,
                "trailing_eps":    info.get("trailingEps"),
                "revenue_growth":  info.get("revenueGrowth"),
                "earnings_growth": info.get("earningsGrowth"),
            }
        except Exception:
            return ticker, {"fetched_date": today}

    with ThreadPoolExecutor(max_workers=max_workers) as ex:
        futures = {ex.submit(_fetch, ticker): ticker for _, ticker in stale}
        for fut in as_completed(futures):
            ticker, data = fut.result()
            cache[ticker] = data

    _save_cache(cache)


def is_fundamentally_weak(ticker: str) -> bool:
    """
    True → 基本面偏弱，建議跳過當沖
    條件：trailing EPS < 0（虧損）
          且 earnings_growth < -20% 或 revenue_growth < -20%（持續惡化）
    ETF / 金融股 / 無資料 → False（不過濾）
    """
    if _is_etf(ticker) or _is_finance(ticker):
        return False

    data = fetch_fundamentals(ticker)
    eps = data.get("trailing_eps")
    if eps is None:
        return False                      # 無資料不過濾

    if eps >= 0:
        return False                      # 有獲利，不過濾

    eg = data.get("earnings_growth")
    rg = data.get("revenue_growth")
    earnings_worsening = eg is not None and eg < -0.20
    revenue_declining  = rg is not None and rg < -0.20

    return earnings_worsening or revenue_declining
