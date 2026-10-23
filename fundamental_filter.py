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
from net_timeout import call_with_timeout

CACHE_FILE    = os.path.join(os.path.dirname(__file__), "fundamental_cache.json")
CACHE_TTL_DAYS = 7
SCHEMA_V = 2          # 欄位結構版本；改欄位時 +1，舊快取自動重抓

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


def _is_fresh_entry(entry: dict) -> bool:
    """舊版快取（沒有 v 或版本較舊）一律視為過期，讓缺的欄位補抓。"""
    return bool(entry) and entry.get("v") == SCHEMA_V and _is_fresh(entry.get("fetched_date", ""))


def _is_fresh(fetched_date: str) -> bool:
    try:
        delta = (datetime.now() - datetime.strptime(fetched_date, "%Y-%m-%d")).days
        return delta < CACHE_TTL_DAYS
    except Exception:
        return False


def _extract(info: dict, today: str) -> dict:
    """yfinance info → 快取欄位。fetch_fundamentals 與 prefetch_all 共用，避免兩邊欄位不一致。"""
    g = info.get
    ni, ocf, fcf = g("netIncomeToCommon"), g("operatingCashflow"), g("freeCashflow")
    mcap = g("marketCap")
    price, target = g("currentPrice") or g("regularMarketPrice"), g("targetMeanPrice")
    return {
        "v":                  SCHEMA_V,
        "fetched_date":       today,
        # 獲利與成長
        "trailing_eps":       g("trailingEps"),
        "revenue_growth":     g("revenueGrowth"),
        "earnings_growth":    g("earningsGrowth"),
        "gross_margins":      g("grossMargins"),
        "operating_margins":  g("operatingMargins"),
        "return_on_equity":   g("returnOnEquity"),
        "return_on_assets":   g("returnOnAssets"),
        # 財務健康
        "debt_to_equity":     g("debtToEquity"),
        "current_ratio":      g("currentRatio"),
        "total_debt":         g("totalDebt"),
        "total_cash":         g("totalCash"),
        # 現金品質（框架 04：帳面盈利是否轉成現金）
        "net_income":         ni,
        "operating_cashflow": ocf,
        "free_cashflow":      fcf,
        "cash_conversion":    round(ocf / ni, 2) if ocf and ni and ni > 0 else None,
        "fcf_yield":          round(fcf / mcap, 4) if fcf and mcap else None,
        # 估值（框架 05）
        "market_cap":         mcap,
        "trailing_pe":        g("trailingPE"),
        "forward_pe":         g("forwardPE"),
        "price_to_book":      g("priceToBook"),
        "ev_to_ebitda":       g("enterpriseToEbitda"),
        "ev_to_revenue":      g("enterpriseToRevenue"),
        "peg":                g("trailingPegRatio") or g("pegRatio"),
        # 持股與分析師
        "insider_pct":        g("heldPercentInsiders"),
        "institution_pct":    g("heldPercentInstitutions"),
        "analyst_count":      g("numberOfAnalystOpinions"),
        "recommendation":     g("recommendationMean"),
        "target_upside":      round(target / price - 1, 4) if target and price else None,
    }


def fetch_fundamentals(ticker: str) -> dict:
    """抓取並快取單檔基本面"""
    cache = _load_cache()
    cached = cache.get(ticker, {})
    if _is_fresh_entry(cached):
        return cached

    today = datetime.now().strftime("%Y-%m-%d")
    try:
        info = call_with_timeout(lambda: yf.Ticker(ticker).info, timeout=45, default=None)
        if not info:
            raise ValueError("逾時或無資料")
        data = _extract(info, today)
    except Exception:
        data = {"v": SCHEMA_V, "fetched_date": today}

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

    # 現金品質：帳面獲利有沒有變成現金
    cc  = data.get("cash_conversion")
    fcf = data.get("free_cashflow")
    if cc is not None:
        if cc < 0.8:
            delta -= 3
            labels.append(f"現金轉換 {cc:.1f}x 偏弱⚠️")
        elif cc >= 1.0:
            labels.append(f"現金轉換 {cc:.1f}x✅")
    if fcf is not None and fcf < 0:
        delta -= 2
        labels.append("自由現金流為負⚠️")

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
        and not _is_fresh_entry(cache.get(ticker, {}))
    ]
    if not stale:
        return

    today = datetime.now().strftime("%Y-%m-%d")

    def _fetch(ticker):
        try:
            info = call_with_timeout(lambda: yf.Ticker(ticker).info, timeout=45, default=None)
            if not info:
                raise ValueError("逾時或無資料")
            return ticker, _extract(info, today)
        except Exception:
            return ticker, {"v": SCHEMA_V, "fetched_date": today}

    with ThreadPoolExecutor(max_workers=max_workers) as ex:
        futures = {ex.submit(_fetch, ticker): ticker for _, ticker in stale}
        for i, fut in enumerate(as_completed(futures), start=1):
            ticker, data = fut.result()
            cache[ticker] = data
            if i % 20 == 0:
                _save_cache(cache)

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
