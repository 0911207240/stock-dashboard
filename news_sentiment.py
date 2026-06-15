"""
新聞情緒分析 — 抓取台股相關新聞標題並做關鍵字情緒評分
資料來源：Yahoo Finance RSS（yfinance）+ TWSE 重大訊息
快取 4 小時（盤中新聞有時效性）

情緒分數：
  +2 per 強利多關鍵字（突破、爆量、法人大買、創新高 …）
  +1 per 輕利多關鍵字（買超、上漲、獲利成長 …）
  -2 per 強利空關鍵字（財報虧損、停牌、減資、法院 …）
  -1 per 輕利空關鍵字（賣超、下跌、警示 …）
最終回傳 sentiment_score（正=偏多/負=偏空）及摘要標籤
"""
import json
import urllib.request
import re
from datetime import datetime
from pathlib import Path

CACHE_FILE     = Path(__file__).parent / "news_sentiment_cache.json"
CACHE_TTL_HOURS = 4

# 關鍵字庫（繁體中文 + 英文）
_STRONG_BULLISH = [
    "創新高", "漲停", "爆量", "大買超", "法人大買", "突破", "營收創高",
    "獲利大增", "EPS創高", "配息", "股利", "業績報喜", "接單滿載",
    "record high", "beat earnings", "strong buy",
]
_MILD_BULLISH = [
    "買超", "上漲", "回升", "止跌", "反彈", "獲利成長", "營收成長",
    "法人買進", "外資買", "投信買", "布局", "拉高",
    "upgrade", "outperform", "buy",
]
_STRONG_BEARISH = [
    "虧損", "財報虧損", "停牌", "減資", "下市", "財務危機", "法院",
    "重大訊息", "違約", "停止交易", "警示股", "全額交割",
    "fraud", "bankruptcy", "delist", "miss earnings",
]
_MILD_BEARISH = [
    "賣超", "下跌", "跌停", "外資賣", "投信賣", "法人賣超", "獲利衰退",
    "營收下滑", "下修", "看空", "空單",
    "downgrade", "underperform", "sell",
]


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


def _is_fresh(fetched_at: str) -> bool:
    try:
        delta_hours = (datetime.now() - datetime.fromisoformat(fetched_at)).total_seconds() / 3600
        return delta_hours < CACHE_TTL_HOURS
    except Exception:
        return False


def _fetch_yahoo_headlines(ticker: str, max_items: int = 10) -> list[str]:
    """透過 Yahoo Finance RSS 抓新聞標題"""
    # Yahoo Finance RSS: https://finance.yahoo.com/rss/headline?s=TICKER
    url = f"https://finance.yahoo.com/rss/headline?s={ticker}"
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=8) as resp:
            xml = resp.read().decode("utf-8", errors="replace")
        titles = re.findall(r'<title><!\[CDATA\[(.*?)\]\]></title>', xml)
        if not titles:
            titles = re.findall(r'<title>(.*?)</title>', xml)
        return [t.strip() for t in titles[1:max_items+1]]  # 第0個是 feed 標題
    except Exception:
        return []


def _fetch_twse_news(stock_code: str, max_items: int = 5) -> list[str]:
    """從 TWSE 重大訊息抓最新公告標題"""
    from twse_announcements import fetch_announcements
    rows = fetch_announcements(stock_code, days_back=3)
    return [r["title"] for r in rows[:max_items]]


def _score_titles(titles: list[str]) -> tuple[int, list[str]]:
    """對新聞標題列表做情緒評分，回傳 (總分, 觸發關鍵字列表)"""
    score   = 0
    matched = []
    combined = " ".join(titles).lower()

    for kw in _STRONG_BULLISH:
        if kw.lower() in combined:
            score += 2
            matched.append(f"+{kw}")
    for kw in _MILD_BULLISH:
        if kw.lower() in combined:
            score += 1
            matched.append(f"+{kw}")
    for kw in _STRONG_BEARISH:
        if kw.lower() in combined:
            score -= 2
            matched.append(f"-{kw}")
    for kw in _MILD_BEARISH:
        if kw.lower() in combined:
            score -= 1
            matched.append(f"-{kw}")

    return score, matched[:6]


def fetch_news_sentiment(stock_code: str) -> dict:
    """
    抓新聞情緒分析，結合 Yahoo RSS + TWSE 公告
    回傳:
      {
        "sentiment_score": int,
        "signal": "bullish" | "bearish" | "neutral",
        "keywords": list[str],
        "headline_count": int,
      }
    """
    code   = stock_code.replace(".TW", "").replace(".TWO", "")
    ticker = stock_code  # 保留原始 ticker（如 2330.TW）

    cache     = _load_cache()
    cache_key = code
    cached    = cache.get(cache_key, {})
    if cached and _is_fresh(cached.get("fetched_at", "")):
        return cached

    # 抓標題
    yahoo_titles = _fetch_yahoo_headlines(ticker)
    twse_titles  = _fetch_twse_news(code) if code.isdigit() else []
    all_titles   = yahoo_titles + twse_titles

    if not all_titles:
        result = {
            "fetched_at":      datetime.now().isoformat(),
            "sentiment_score": 0,
            "signal":          "neutral",
            "keywords":        [],
            "headline_count":  0,
        }
        cache[cache_key] = result
        _save_cache(cache)
        return result

    score, keywords = _score_titles(all_titles)

    if score >= 3:
        signal = "strong_bullish"
    elif score >= 1:
        signal = "bullish"
    elif score <= -3:
        signal = "strong_bearish"
    elif score <= -1:
        signal = "bearish"
    else:
        signal = "neutral"

    result = {
        "fetched_at":      datetime.now().isoformat(),
        "sentiment_score": score,
        "signal":          signal,
        "keywords":        keywords,
        "headline_count":  len(all_titles),
        "sample_headlines": all_titles[:3],
    }
    cache[cache_key] = result
    _save_cache(cache)
    return result


def get_sentiment_score_delta(stock_code: str) -> dict:
    """
    回傳評分用資料
    {
      "score_delta": int,   # 對總分加/減分（最大 ±8）
      "label": str,
    }
    """
    data = fetch_news_sentiment(stock_code)
    sig  = data.get("signal", "neutral")
    score = data.get("sentiment_score", 0)
    kws  = data.get("keywords", [])
    kw_str = " ".join(kws[:3]) if kws else ""

    delta_map = {
        "strong_bullish": 8,
        "bullish":        4,
        "neutral":        0,
        "bearish":       -4,
        "strong_bearish":-8,
    }
    delta = delta_map.get(sig, 0)

    label_map = {
        "strong_bullish": f"📰 新聞強勢偏多（{kw_str}）",
        "bullish":        f"📰 新聞偏多（{kw_str}）",
        "neutral":        "",
        "bearish":        f"📰 新聞偏空（{kw_str}）",
        "strong_bearish": f"📰 新聞強勢偏空⚠️（{kw_str}）",
    }
    return {
        "score_delta": delta,
        "label":       label_map.get(sig, ""),
        "signal":      sig,
    }
