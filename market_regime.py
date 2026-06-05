"""
大盤狀態分層模組
偵測台股加權指數目前處於多頭 / 盤整 / 空頭
並回傳對應的當沖評分門檻調整值與說明
"""
import pandas as pd
import yfinance as yf


def fetch_vix() -> float | None:
    """抓 CBOE VIX 最新收盤值，失敗回傳 None"""
    try:
        df = yf.download("^VIX", period="5d", interval="1d", progress=False)
        if df.empty:
            return None
        df.columns = [c[0] if isinstance(c, tuple) else c for c in df.columns]
        return round(float(df["Close"].iloc[-1]), 1)
    except Exception:
        return None


def vix_label(vix: float) -> tuple[str, int]:
    """
    回傳 (描述文字, 門檻加成)
    VIX > 30：極度恐慌，當沖門檻再 +10
    VIX > 20：偏高，+5
    VIX < 15：貪婪區，-5
    """
    if vix > 30:
        return f"😱 VIX {vix}（極度恐慌）", +10
    if vix > 20:
        return f"😰 VIX {vix}（市場偏恐慌）", +5
    if vix < 15:
        return f"😎 VIX {vix}（市場貪婪）", -5
    return f"😐 VIX {vix}（中性）", 0


def futures_label(net: int) -> tuple[str, int]:
    """
    依外資台指期淨口數回傳 (描述, 門檻調整)
    大多：net > 30,000 → -5；偏多：> 10,000 → -2
    偏空：< -10,000 → +5；大空：< -30,000 → +10
    """
    if net > 30_000:
        return f"🐂 外資期貨強多 +{net:,} 口", -5
    if net > 10_000:
        return f"📈 外資期貨偏多 +{net:,} 口", -2
    if net >= 0:
        return f"➡️ 外資期貨小多 +{net:,} 口", 0
    if net > -10_000:
        return f"📉 外資期貨偏空 {net:,} 口", +5
    if net > -30_000:
        return f"🐻 外資期貨空頭 {net:,} 口", +8
    return f"🐻 外資期貨強空 {net:,} 口", +10


def detect_regime(df: pd.DataFrame, futures_data: dict = None) -> dict:
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

    latest   = df.iloc[-1]
    lookback = df.iloc[-5] if len(df) >= 5 else df.iloc[0]

    close = float(latest["Close"])
    ma5   = float(latest.get("MA5",  close)) if pd.notna(latest.get("MA5"))  else close
    ma20  = float(latest.get("MA20", close)) if pd.notna(latest.get("MA20")) else close
    ma60  = float(latest.get("MA60", close)) if pd.notna(latest.get("MA60")) else close

    dev_ma20   = (close - ma20) / ma20 * 100
    momentum5d = (close - float(lookback["Close"])) / float(lookback["Close"]) * 100

    bull_align = ma5 > ma20 > ma60
    bear_align = ma5 < ma20

    # VIX 恐慌指數修正
    vix      = fetch_vix()
    vix_desc, vix_adj = vix_label(vix) if vix is not None else ("VIX 無資料", 0)

    # 台指期外資部位修正
    futures_net  = futures_data.get("foreign_net", 0) if futures_data else 0
    futures_desc, fut_adj = futures_label(futures_net) if futures_data else ("期貨無資料", 0)

    # ── 多頭：均線多頭排列 + 站上MA20 + 近5日未大跌
    if bull_align and close > ma20 and momentum5d > -3:
        adj = -5 + vix_adj + fut_adj
        return {
            "state":         "多頭",
            "emoji":         "🟢",
            "description":   f"均線多頭排列（近5日 {momentum5d:+.1f}%）｜{vix_desc}",
            "min_score_adj": adj,
            "close":         close,
            "dev_ma20_pct":  round(dev_ma20,   1),
            "momentum_5d":   round(momentum5d, 1),
            "vix":           vix,
            "futures_net":   futures_net,
            "futures_desc":  futures_desc,
        }

    # ── 空頭：均線空頭 + 跌破MA20超過3%
    if bear_align and dev_ma20 < -3:
        adj = 15 + vix_adj + fut_adj
        return {
            "state":         "空頭",
            "emoji":         "🔴",
            "description":   f"均線空頭（距MA20 {dev_ma20:.1f}%）｜{vix_desc}",
            "min_score_adj": adj,
            "close":         close,
            "dev_ma20_pct":  round(dev_ma20,   1),
            "momentum_5d":   round(momentum5d, 1),
            "vix":           vix,
            "futures_net":   futures_net,
            "futures_desc":  futures_desc,
        }

    # ── 盤整：其他情況
    return {
        "state":         "盤整",
        "emoji":         "🟡",
        "description":   f"大盤盤整（近5日 {momentum5d:+.1f}%）｜{vix_desc}",
        "min_score_adj": vix_adj + fut_adj,
        "close":         close,
        "dev_ma20_pct":  round(dev_ma20,   1),
        "momentum_5d":   round(momentum5d, 1),
        "vix":           vix,
        "futures_net":   futures_net,
        "futures_desc":  futures_desc,
    }


def _neutral() -> dict:
    return {
        "state": "盤整", "emoji": "🟡",
        "description": "大盤資料不足，採預設門檻",
        "min_score_adj": 0, "close": 0,
        "dev_ma20_pct": 0, "momentum_5d": 0,
    }
