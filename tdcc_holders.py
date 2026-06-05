"""TDCC 集保戶數分析 — 每週五更新，追蹤大戶籌碼集中度變化"""
import json, re, urllib.request, urllib.parse
from datetime import datetime, timedelta
from pathlib import Path

CACHE_FILE = Path("tdcc_cache.json")


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


def _last_friday_str() -> str:
    today = datetime.now()
    days_since_friday = (today.weekday() - 4) % 7
    return (today - timedelta(days=days_since_friday)).strftime("%Y%m%d")


def _fetch_one(code: str, date_str: str) -> dict:
    url = "https://www.tdcc.com.tw/smWeb/QryStockAjax.do"
    post_data = urllib.parse.urlencode({
        "scaDates":              date_str,
        "scaDate":               date_str,
        "SqlMethod":             "StockHolders",
        "StockNo":               code,
        "clkQryStockHoldersBtn": "1",
    }).encode("utf-8")
    try:
        req = urllib.request.Request(url, data=post_data, headers={
            "User-Agent":   "Mozilla/5.0",
            "Content-Type": "application/x-www-form-urlencoded",
        })
        with urllib.request.urlopen(req, timeout=10) as resp:
            html = resp.read().decode("utf-8", errors="replace")
        return _parse_html(html, date_str)
    except Exception:
        return {}


def _parse_html(html: str, date_str: str) -> dict:
    def _int(s):
        try:
            return int(str(s).replace(",", "").strip())
        except Exception:
            return 0

    rows = re.findall(r'<tr[^>]*>(.*?)</tr>', html, re.DOTALL)
    big_shares = small_shares = total_shares = total_holders = 0

    for row in rows:
        tds   = re.findall(r'<td[^>]*>(.*?)</td>', row, re.DOTALL)
        clean = [re.sub(r'<[^>]+>', '', td).strip() for td in tds]
        if len(clean) < 3:
            continue
        try:
            level = int(clean[0])
        except Exception:
            continue
        holders = _int(clean[1])
        shares  = _int(clean[2])
        total_holders += holders
        total_shares  += shares
        if level <= 2:    # 1–5,000 股（散戶 <5 張）
            small_shares += shares
        if level >= 12:   # 400,001+ 股（大戶 >400 張）
            big_shares += shares

    if total_shares == 0:
        return {}
    return {
        "date":          date_str,
        "big_pct":       round(big_shares   / total_shares * 100, 2),
        "small_pct":     round(small_shares / total_shares * 100, 2),
        "total_holders": total_holders,
    }


def fetch_tdcc_holders(stock_code: str) -> dict:
    """
    抓個股最新週持股集中度（附快取，同週只打一次 API）
    回傳: {"date", "big_pct", "small_pct", "total_holders"} 或 {}
    """
    code = stock_code.replace(".TW", "").replace(".TWO", "")
    if "." in code:
        return {}

    cache      = _load_cache()
    target_fri = _last_friday_str()
    cache_key  = f"{code}_{target_fri}"

    if cache_key in cache:
        return cache[cache_key]

    # 嘗試最近 3 週的週五（防假日或延遲更新）
    for weeks_back in range(3):
        fri = (datetime.strptime(target_fri, "%Y%m%d") - timedelta(weeks=weeks_back)).strftime("%Y%m%d")
        result = _fetch_one(code, fri)
        if result:
            cache[cache_key] = result
            _save_cache(cache)
            return result
    return {}


def get_holder_signal(stock_code: str) -> dict:
    """
    回傳大戶週變化訊號
    回傳: {
        "big_pct":    float | None,
        "big_change": float | None,   # 本週 vs 上週大戶持股比例差
        "signal":     "accumulate" | "distribute" | "neutral" | "unknown",
        "label":      str,
    }
    """
    code    = stock_code.replace(".TW", "").replace(".TWO", "")
    current = fetch_tdcc_holders(stock_code)
    if not current:
        return {"signal": "unknown", "label": "", "big_pct": None, "big_change": None}

    # 取上週資料（優先從快取讀，避免重複 API）
    cache        = _load_cache()
    current_fri  = datetime.strptime(current["date"], "%Y%m%d")
    prev_fri_str = (current_fri - timedelta(weeks=1)).strftime("%Y%m%d")
    prev_key     = f"{code}_{prev_fri_str}"

    prev = cache.get(prev_key) or _fetch_one(code, prev_fri_str)
    if prev and prev_key not in cache:
        cache[prev_key] = prev
        _save_cache(cache)

    big_change = None
    signal     = "neutral"
    label      = f"大戶 {current['big_pct']}%"

    if prev and prev.get("big_pct") is not None:
        big_change = round(current["big_pct"] - prev["big_pct"], 2)
        sign       = "+" if big_change >= 0 else ""
        label      = f"大戶 {current['big_pct']}%（週變 {sign}{big_change}%）"
        if big_change >= 0.5:
            signal = "accumulate"
            label  = f"📦 集保大戶增持 +{big_change}%（共 {current['big_pct']}%）"
        elif big_change <= -0.5:
            signal = "distribute"
            label  = f"📤 集保大戶減持 {big_change}%（共 {current['big_pct']}%）"

    return {
        "big_pct":    current["big_pct"],
        "big_change": big_change,
        "signal":     signal,
        "label":      label,
    }
