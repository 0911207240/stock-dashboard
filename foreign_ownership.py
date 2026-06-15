"""
外資持股比例趨勢 — 從 TWSE MI_QFIIS 抓每日外資持股比例
追蹤 4 週持股變化斜率，判斷外資長期布局意圖

重要性：
  外資單日買超可能是避險/套利，不代表長期看多
  但外資持股比例連續 4 週增加 → 真正的長期布局訊號（更可靠）

快取策略：每檔每日更新，保留最近 30 天歷史
"""
import json
import urllib.request
from datetime import datetime, timedelta
from pathlib import Path

CACHE_FILE     = Path(__file__).parent / "foreign_ownership_cache.json"
CACHE_TTL_DAYS = 1   # 每日更新


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


def _fetch_qfiis_day(date_str: str) -> dict[str, float]:
    """
    抓 TWSE MI_QFIIS 指定日期全市場外資持股比例
    回傳 {股票代號: 持股比例%}
    """
    url = (
        f"https://www.twse.com.tw/rwd/zh/fund/MI_QFIIS"
        f"?date={date_str}&selectType=ALL&response=json"
    )
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=12) as resp:
            data = json.loads(resp.read())
        if data.get("stat") != "OK" or not data.get("data"):
            return {}
        result = {}
        for row in data["data"]:
            if len(row) < 5:
                continue
            code = row[0].strip()
            try:
                pct = float(str(row[4]).replace(",", "").replace("%", ""))
                if 0 <= pct <= 100:
                    result[code] = pct
            except (ValueError, IndexError):
                continue
        return result
    except Exception:
        return {}


def _get_day_data(date_str: str, cache: dict) -> dict[str, float]:
    """從快取取當日資料，快取過期才重新抓"""
    key   = f"day_{date_str}"
    entry = cache.get(key, {})
    if entry.get("fetched") and entry.get("data"):
        return entry["data"]
    data = _fetch_qfiis_day(date_str)
    if data:
        cache[key] = {"fetched": datetime.now().isoformat(), "data": data}
        _save_cache(cache)
    return data


def fetch_foreign_ownership_trend(stock_code: str, weeks: int = 4) -> dict:
    """
    抓個股最近 weeks 週的外資持股比例，計算趨勢
    回傳：
    {
      "current_pct":  float,    # 最新外資持股比例
      "change_4w":    float,    # 4週變化（百分點）
      "slope":        float,    # 週均斜率（持股/週）
      "signal":       "accumulating" | "distributing" | "neutral",
      "label":        str,
    }
    """
    code  = stock_code.replace(".TW", "").replace(".TWO", "")
    if not code.isdigit():
        return {}

    cache = _load_cache()

    # 取最近 weeks*7+5 天，挑選有資料的交易日（最多取 weeks 個點）
    pct_history = []
    for i in range(weeks * 7 + 5):
        date_str = (datetime.now() - timedelta(days=i)).strftime("%Y%m%d")
        day_data = _get_day_data(date_str, cache)
        if code in day_data:
            pct_history.append((date_str, day_data[code]))
        if len(pct_history) >= weeks * 5:   # 蒐集夠多就停
            break

    if len(pct_history) < 2:
        return {}

    current_pct = pct_history[0][1]
    oldest_pct  = pct_history[-1][1]
    change      = round(current_pct - oldest_pct, 2)
    slope       = round(change / max(len(pct_history) / 5, 1), 3)  # 每週斜率

    if change >= 2.0 or slope >= 0.4:
        signal = "accumulating"
        label  = f"📥 外資持股 {current_pct:.1f}%（{weeks}週+{change:.1f}ppt，持續增持）"
    elif change <= -2.0 or slope <= -0.4:
        signal = "distributing"
        label  = f"📤 外資持股 {current_pct:.1f}%（{weeks}週{change:.1f}ppt，持續減持）"
    else:
        signal = "neutral"
        label  = f"外資持股 {current_pct:.1f}%（{weeks}週變{change:+.1f}ppt）"

    return {
        "current_pct": current_pct,
        "change_4w":   change,
        "slope":       slope,
        "signal":      signal,
        "label":       label,
    }


def get_ownership_score_delta(stock_code: str) -> dict:
    """
    回傳評分加分 (最大 ±8)
    {score_delta, label, signal}
    """
    data = fetch_foreign_ownership_trend(stock_code)
    if not data:
        return {"score_delta": 0, "label": "", "signal": "unknown"}

    signal = data.get("signal", "neutral")
    delta_map = {"accumulating": 8, "neutral": 0, "distributing": -8}

    return {
        "score_delta": delta_map.get(signal, 0),
        "label":       data.get("label", ""),
        "signal":      signal,
    }
