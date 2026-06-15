"""
美股夜盤連動分析 — 抓取費半/那斯達克/那斯達克期貨/S&P500 前一交易日走勢
用於預測台股開盤方向，調整當沖評分門檻

連動邏輯：
  費半（SOX）與台灣半導體高度相關（r ≈ 0.85）
  那斯達克（IXIC）與科技股連動
  夜盤全面大跌 → 台股開盤重壓，提高門檻
  夜盤全面大漲 → 台股開盤偏多，降低門檻
"""
import yfinance as yf
from datetime import datetime


_INDICES = {
    "SOX":    ("^SOX",   "費城半導體"),
    "NASDAQ": ("^IXIC",  "那斯達克"),
    "NQ":     ("NQ=F",   "那斯達克期貨"),
    "SP500":  ("^GSPC",  "S&P500"),
}


def fetch_us_overnight() -> dict:
    """
    抓取美股主要指數最新一日漲跌幅（台股開盤前已收盤）
    回傳：
    {
      "indices": {
        "SOX":    {"name": str, "chg_pct": float},
        "NASDAQ": {...},
        "NQ":     {...},
        "SP500":  {...},
      },
      "overall_signal": "strong_bull" | "bull" | "neutral" | "bear" | "strong_bear",
      "score_adj":      int,    # 對評分門檻的調整值（正=提高門檻/偏空）
      "summary":        str,    # 一行摘要
    }
    """
    indices_result = {}
    chg_list = []

    for key, (ticker, name) in _INDICES.items():
        try:
            df = yf.download(ticker, period="5d", interval="1d", progress=False)
            if df.empty or len(df) < 2:
                continue
            cols = [c[0] if isinstance(c, tuple) else c for c in df.columns]
            df.columns = cols
            close = df["Close"].dropna()
            if len(close) < 2:
                continue
            chg = (float(close.iloc[-1]) - float(close.iloc[-2])) / float(close.iloc[-2]) * 100
            chg = round(chg, 2)
            indices_result[key] = {"name": name, "chg_pct": chg}
            chg_list.append(chg)
        except Exception:
            continue

    if not chg_list:
        return {
            "indices": {},
            "overall_signal": "neutral",
            "score_adj": 0,
            "summary": "美股資料暫無",
        }

    # SOX 權重最高（台股半導體連動最強），其餘平均
    sox_chg = indices_result.get("SOX", {}).get("chg_pct", 0)
    avg_chg = sum(chg_list) / len(chg_list)
    # 加權：SOX 佔 50%，整體平均佔 50%
    weighted = sox_chg * 0.5 + avg_chg * 0.5

    # 訊號判斷
    if weighted >= 2.0:
        signal   = "strong_bull"
        score_adj = -8
    elif weighted >= 0.8:
        signal   = "bull"
        score_adj = -4
    elif weighted <= -2.0:
        signal   = "strong_bear"
        score_adj = +10
    elif weighted <= -0.8:
        signal   = "bear"
        score_adj = +5
    else:
        signal   = "neutral"
        score_adj = 0

    # 摘要
    emoji_map = {
        "strong_bull": "🚀",
        "bull":        "📈",
        "neutral":     "➡️",
        "bear":        "📉",
        "strong_bear": "🔻",
    }
    parts = []
    for key in ("SOX", "NASDAQ", "SP500"):
        d = indices_result.get(key)
        if d:
            sign = "+" if d["chg_pct"] >= 0 else ""
            parts.append(f"{d['name']} {sign}{d['chg_pct']:.1f}%")
    summary = f"{emoji_map[signal]} 美股夜盤：{'｜'.join(parts)}"

    return {
        "indices":        indices_result,
        "overall_signal": signal,
        "score_adj":      score_adj,
        "summary":        summary,
        "weighted_chg":   round(weighted, 2),
    }


def us_overnight_label(data: dict) -> tuple[str, int]:
    """回傳 (摘要文字, 門檻調整值) 供 market_regime 使用"""
    if not data or not data.get("indices"):
        return "美股資料暫無", 0
    return data.get("summary", ""), data.get("score_adj", 0)
