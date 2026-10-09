"""
反方分析師：專門替每檔候選找「為什麼不該買」的理由。目前只記錄，不影響推播分數。
每條異議用短代碼存進影子紀錄（bear 欄位），之後由績效部驗證「異議越多是否報酬越差」。
"""
import pandas as pd

# 代碼 → 說明（報告用）
OBJECTIONS = {
    "chase":     "近3日已漲超過8%，追高風險",
    "wall":      "距近60日高點不到2%，上方壓力區",
    "vol_stall": "爆量（量比≥3）但漲幅不到1%，疑似出貨",
    "weak_rs":   "5日、20日皆弱於大盤",
    "deep_mdd":  "近20日最大回撤超過15%，走勢不穩",
    "earnings":  "財報3日內，波動風險高",
    "bad_hist":  "個股歷史勝率低於40%",
    "bear_mkt":  "大盤處於空頭",
    "gap_up":    "昨日開高幅度過大（缺口≥4%），隔日回補機率高",
}


def challenge(c: dict, df: pd.DataFrame, regime: dict = None) -> list[str]:
    """回傳異議代碼清單。df 為含 Close/High/Open 的日K，缺資料時略過該條。"""
    out = []
    try:
        close = df["Close"].astype(float)
        if len(close) >= 4:
            gain3 = (close.iloc[-1] / close.iloc[-4] - 1) * 100
            if gain3 > 8:
                out.append("chase")
        if len(df) >= 60:
            hi60 = float(df["High"].astype(float).iloc[-60:].max())
            if hi60 > 0 and 0 <= (hi60 - close.iloc[-1]) / hi60 * 100 < 2:
                out.append("wall")
        if len(df) >= 2 and "Open" in df:
            prev_c = float(close.iloc[-2])
            if prev_c > 0 and (float(df["Open"].iloc[-1]) / prev_c - 1) * 100 >= 4:
                out.append("gap_up")
    except Exception:
        pass

    if (c.get("vol_ratio") or 0) >= 3 and (c.get("change_pct") or 0) < 1:
        out.append("vol_stall")
    if (c.get("rs5") or 1) < 0.98 and (c.get("rs20") or 1) < 0.95:
        out.append("weak_rs")
    if (c.get("mdd_20") or 0) > 15:
        out.append("deep_mdd")
    if c.get("earnings_risk"):
        out.append("earnings")
    hw = c.get("hist_wr")
    if hw is not None and hw < 40:
        out.append("bad_hist")
    if (regime or {}).get("state") == "空頭":
        out.append("bear_mkt")
    return out
