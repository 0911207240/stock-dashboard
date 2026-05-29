"""
大盤狀態分層模組
偵測台股加權指數目前處於多頭 / 盤整 / 空頭
並回傳對應的當沖評分門檻調整值與說明
"""
import pandas as pd


def detect_regime(df: pd.DataFrame) -> dict:
    """
    輸入：add_indicators 處理後的 TAIEX DataFrame
    輸出：
      state          : "多頭" | "盤整" | "空頭"
      emoji          : 圖示
      description    : 一行說明
      min_score_adj  : 當沖評分門檻調整值（加上基準 40 後使用）
      close          : 最新指數
      dev_ma20_pct   : 距 MA20 偏離 %
      momentum_5d    : 近 5 日漲跌 %
    """
    if df is None or len(df) < 20:
        return _neutral()

    latest = df.iloc[-1]
    lookback = df.iloc[-5] if len(df) >= 5 else df.iloc[0]

    close = float(latest["Close"])
    ma5   = float(latest.get("MA5",  close)) if pd.notna(latest.get("MA5"))  else close
    ma20  = float(latest.get("MA20", close)) if pd.notna(latest.get("MA20")) else close
    ma60  = float(latest.get("MA60", close)) if pd.notna(latest.get("MA60")) else close

    dev_ma20   = (close - ma20) / ma20 * 100
    momentum5d = (close - float(lookback["Close"])) / float(lookback["Close"]) * 100

    bull_align = ma5 > ma20 > ma60
    bear_align = ma5 < ma20

    # ── 多頭：均線多頭排列 + 站上MA20 + 近5日未大跌
    if bull_align and close > ma20 and momentum5d > -3:
        return {
            "state":         "多頭",
            "emoji":         "🟢",
            "description":   f"均線多頭排列，指數強勢（近5日 {momentum5d:+.1f}%）",
            "min_score_adj": -5,     # 門檻降至 35，機會更多
            "close":         close,
            "dev_ma20_pct":  round(dev_ma20,   1),
            "momentum_5d":   round(momentum5d, 1),
        }

    # ── 空頭：均線空頭 + 跌破MA20超過3%
    if bear_align and dev_ma20 < -3:
        return {
            "state":         "空頭",
            "emoji":         "🔴",
            "description":   f"均線空頭，指數偏弱（距MA20 {dev_ma20:.1f}%）",
            "min_score_adj": +15,    # 門檻升至 55，只做最強標的
            "close":         close,
            "dev_ma20_pct":  round(dev_ma20,   1),
            "momentum_5d":   round(momentum5d, 1),
        }

    # ── 盤整：其他情況
    return {
        "state":         "盤整",
        "emoji":         "🟡",
        "description":   f"大盤盤整，方向未明（近5日 {momentum5d:+.1f}%）",
        "min_score_adj": 0,
        "close":         close,
        "dev_ma20_pct":  round(dev_ma20,   1),
        "momentum_5d":   round(momentum5d, 1),
    }


def _neutral() -> dict:
    return {
        "state": "盤整", "emoji": "🟡",
        "description": "大盤資料不足，採預設門檻",
        "min_score_adj": 0, "close": 0,
        "dev_ma20_pct": 0, "momentum_5d": 0,
    }
