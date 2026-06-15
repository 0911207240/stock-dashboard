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
    """抓取並快取單檔基本面（含擴充的毛利率/ROE/負債比）"""
    cache = _load_cache()
    cached = cache.get(ticker, {})
    if cached and _is_fresh(cached.get("fetched_date", "")):
        return cached

    today = datetime.now().strftime("%Y-%m-%d")
    try:
        info = yf.Ticker(ticker).info
        data = {
            "fetched_date":       today,
            # 原有欄位
            "trailing_eps":       info.get("trailingEps"),
            "revenue_growth":     info.get("revenueGrowth"),
            "earnings_growth":    info.get("earningsGrowth"),
            # 新增：獲利品質
            "gross_margins":      info.get("grossMargins"),        # 毛利率
            "operating_margins":  info.get("operatingMargins"),    # 營業利益率
            "return_on_equity":   info.get("returnOnEquity"),      # ROE
            "return_on_assets":   info.get("returnOnAssets"),      # ROA
            # 新增：財務健康
            "debt_to_equity":     info.get("debtToEquity"),        # 負債/股東權益
            "current_ratio":      info.get("currentRatio"),        # 流動比率
            # 新增：估值
            "trailing_pe":        info.get("trailingPE"),          # 本益比
            "price_to_book":      info.get("priceToBook"),         # 股價淨值比
            "forward_pe":         info.get("forwardPE"),           # 預估本益比
        }
    except Exception:
        data = {"fetched_date": today}

    cache[ticker] = data
    _save_cache(cache)
    return data


def get_fundamental_score(ticker: str) -> dict:
    """
    根據基本面指標計算加減分與標籤
    回傳：{score_delta: int, labels: list[str], grade: str}
    - 毛利率 > 40%：+5（高護城河）
    - ROE > 15%：+5（高效益）
    - 負債比過高（D/E > 200%）：-5
    - 本益比過高（PE > 40）：-3
    grade：A / B / C / D / unknown
    """
    if _is_etf(ticker) or _is_finance(ticker):
        return {"score_delta": 0, "labels": [], "grade": "unknown"}

    data   = fetch_fundamentals(ticker)
    delta  = 0
    labels = []

    gm  = data.get("gross_margins")
    roe = data.get("return_on_equity")
    de  = data.get("debt_to_equity")
    pe  = data.get("trailing_pe")
    cr  = data.get("current_ratio")
    om  = data.get("operating_margins")

    # 毛利率
    if gm is not None:
        if gm >= 0.4:
            delta += 5
            labels.append(f"毛利率 {gm*100:.0f}%✅")
        elif gm >= 0.2:
            labels.append(f"毛利率 {gm*100:.0f}%")
        elif gm < 0.1:
            delta -= 3
            labels.append(f"毛利率偏低 {gm*100:.0f}%⚠️")

    # ROE
    if roe is not None:
        if roe >= 0.20:
            delta += 5
            labels.append(f"ROE {roe*100:.0f}%✅")
        elif roe >= 0.12:
            delta += 2
            labels.append(f"ROE {roe*100:.0f}%")
        elif roe < 0:
            delta -= 3
            labels.append(f"ROE負值⚠️")

    # 負債比
    if de is not None:
        if de > 200:
            delta -= 5
            labels.append(f"負債比 {de:.0f}%⚠️")
        elif de > 100:
            delta -= 2
            labels.append(f"負債比 {de:.0f}%")

    # 本益比
    if pe is not None and pe > 0:
        if pe > 50:
            delta -= 3
            labels.append(f"PE {pe:.0f}x 偏高")
        elif pe < 10:
            delta += 2
            labels.append(f"PE {pe:.0f}x 低估")

    # 流動比率
    if cr is not None and cr < 1.0:
        delta -= 3
        labels.append(f"流動比 {cr:.1f} 短期償債偏弱⚠️")

    # 綜合評級
    if delta >= 8:
        grade = "A"
    elif delta >= 4:
        grade = "B"
    elif delta >= 0:
        grade = "C"
    else:
        grade = "D"

    return {"score_delta": max(-10, min(10, delta)), "labels": labels, "grade": grade}


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
