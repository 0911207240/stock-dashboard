"""
反方分析師：專門替每檔候選找「為什麼不該買」的理由。目前只記錄，不影響推播分數。
每條異議用短代碼存進影子紀錄（bear 欄位），之後由績效部驗證「異議越多是否報酬越差」。

兩類異議：
  技術面（chase、wall…）：看日K，短線追價風險
  基本面（f_ 開頭）：只讀基本面快取、不連網，抓估值過高、獲利沒變現金、負債高等體質問題
另外 kill_conditions() 替每檔寫出「出現什麼就代表看多論點失效」的可檢查條件（含具體價位），
存進影子紀錄 kill 欄位，事後可逐條核對哪一條先被觸發。
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
    # 基本面（框架 06：估值過高、會計紅旗、增長放緩、負債、現金轉換差）
    "f_rich":    "估值偏高（本益比>50 或 EV/EBITDA>30）",
    "f_cash":    "獲利沒轉成現金（營運現金流／淨利 < 0.8）",
    "f_fcf":     "自由現金流為負",
    "f_debt":    "負債比 > 200%",
    "f_slow":    "營收衰退（年增率 < 0）",
    "f_loss":    "近四季虧損",
    "f_margin":  "毛利率 < 10%，沒有定價能力",
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


def _fund(ticker: str) -> dict:
    """只讀快取，不連網（掃描前 prefetch_all 已更新快取）。"""
    try:
        from fundamental_filter import _load_cache
        return _load_cache().get(ticker, {}) or {}
    except Exception:
        return {}


def challenge_fundamentals(ticker: str) -> list[str]:
    """回傳基本面異議代碼。ETF、金融股、無資料時回傳空清單。"""
    try:
        from fundamental_filter import _is_etf, _is_finance
        if _is_etf(ticker) or _is_finance(ticker):
            return []
    except Exception:
        pass
    f = _fund(ticker)
    if not f:
        return []
    out = []
    pe, ev = f.get("trailing_pe"), f.get("ev_to_ebitda")
    if (pe is not None and pe > 50) or (ev is not None and ev > 30):
        out.append("f_rich")
    cc = f.get("cash_conversion")
    if cc is not None and cc < 0.8:
        out.append("f_cash")
    fcf = f.get("free_cashflow")
    if fcf is not None and fcf < 0:
        out.append("f_fcf")
    de = f.get("debt_to_equity")
    if de is not None and de > 200:
        out.append("f_debt")
    rg = f.get("revenue_growth")
    if rg is not None and rg < 0:
        out.append("f_slow")
    eps = f.get("trailing_eps")
    if eps is not None and eps < 0:
        out.append("f_loss")
    gm = f.get("gross_margins")
    if gm is not None and gm < 0.10:
        out.append("f_margin")
    return out


def kill_conditions(c: dict, df: pd.DataFrame) -> list[str]:
    """看多論點的失效條件，寫成可檢查的價位或數字。任一條成立＝論點失效、不該再拗。"""
    out = []
    stop = c.get("stop")
    if stop:
        out.append(f"盤中跌破停損 {stop:.2f}")
    em = c.get("entry_mid")
    if em:
        out.append(f"開盤即低於進場價 {em:.2f} 且 30 分鐘內站不回")
    try:
        close = df["Close"].astype(float)
        if len(close) >= 20:
            ma20 = float(close.iloc[-20:].mean())
            out.append(f"收盤跌破 20 日均線 {ma20:.2f}")
        if len(df) >= 2 and "Low" in df:
            out.append(f"收盤跌破昨日低點 {float(df['Low'].astype(float).iloc[-1]):.2f}")
    except Exception:
        pass
    vr = c.get("vol_ratio")
    if vr and vr >= 1.5:
        out.append("隔日量比掉到 1 以下（追價買盤消失）")
    return out
