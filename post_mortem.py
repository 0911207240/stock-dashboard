"""
事後檢討官：把近期「推播後停損」的單分類成 運氣／判斷錯／執行錯，讓檢討有固定格式。
大盤基準用影子紀錄當日候選池的 T+1 中位數（候選池 60 檔，足以代表當天整體走勢）。
"""
import pandas as pd

MARKET_DOWN = -1.0   # 當日候選池 T+1 中位數低於此視為大盤/全面下跌


def classify(df: pd.DataFrame, history: list, days: int = 7) -> dict:
    """df：影子紀錄（含 r1、bear 欄位）；history：daytrade_history。回傳分類統計與最差個案。"""
    if not history:
        return {"n": 0}
    h = pd.DataFrame(history)
    h = h[h["result"] == "停損"]
    if h.empty:
        return {"n": 0}
    cutoff = (pd.Timestamp.now() - pd.Timedelta(days=days)).strftime("%Y-%m-%d")
    h = h[h["push_date"] >= cutoff]
    if h.empty:
        return {"n": 0}

    day_med = {}
    lookup = {}
    if df is not None and not df.empty and "r1" in df:
        day_med = df.groupby("date")["r1"].median().to_dict()
        lookup = {(r["date"], r["ticker"]): r for _, r in df.iterrows()}

    cats = {"大盤因素（運氣）": [], "停損過緊（收盤反彈）": [], "反方早有警告": [], "訊號判斷錯": []}
    for _, e in h.iterrows():
        rec = lookup.get((e["push_date"], e["ticker"]))
        med = day_med.get(e["push_date"])
        tag = "訊號判斷錯"
        if med is not None and pd.notna(med) and med <= MARKET_DOWN:
            tag = "大盤因素（運氣）"
        elif rec is not None and pd.notna(rec.get("r1")) and rec["r1"] > 0:
            tag = "停損過緊（收盤反彈）"
        elif rec is not None and isinstance(rec.get("bear"), list) and len(rec["bear"]) >= 2:
            tag = "反方早有警告"
        cats[tag].append(f"{e['name']}（{e['push_date']}，{e['score']}分，{e['return_pct']:+.2f}%）")

    worst = h.sort_values("return_pct").head(3)
    return {
        "n": len(h),
        "cats": {k: v for k, v in cats.items() if v},
        "worst": [f"{r['name']} {r['push_date']} {r['return_pct']:+.2f}%" for _, r in worst.iterrows()],
    }
