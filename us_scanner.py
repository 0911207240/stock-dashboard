"""美股夜盤掃描（台灣時間每日 05:30 執行，對應美股收盤後）"""
import json
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from pathlib import Path
from data_fetcher import fetch, WATCHLIST, ensure_yf_warmup
from analyzer import add_indicators, detect_signals, score, calc_week52

US_WATCHLIST = {k: v for k, v in WATCHLIST.items() if not v.endswith(".TW") and not v.endswith(".TWO")}
_US_RESULTS = Path("us_scan_results.json")


def _attach_valuation(found: list):
    """
    框架 05：替有技術訊號的美股補上估值與現金品質，並標出基本面異議。
    只附在結果檔供儀表板參考，不改變分數或排序。基本面快取 7 天，平常不會重抓。
    """
    if not found:
        return
    try:
        from fundamental_filter import fetch_fundamentals
        from devils_advocate import challenge_fundamentals
    except Exception:
        return
    with ThreadPoolExecutor(max_workers=4) as pool:
        funds = dict(zip([x["ticker"] for x in found],
                         pool.map(lambda x: fetch_fundamentals(x["ticker"]), found)))
    keys = ("trailing_pe", "forward_pe", "ev_to_ebitda", "peg", "fcf_yield",
            "cash_conversion", "revenue_growth", "target_upside", "recommendation")
    for x in found:
        f = funds.get(x["ticker"]) or {}
        x["valuation"] = {k: f.get(k) for k in keys if f.get(k) is not None}
        x["bear"] = challenge_fundamentals(x["ticker"])


def run_us_scan(min_score: int = 2, notify: bool = True):
    print(f"\n[{datetime.now().strftime('%Y-%m-%d %H:%M')}] 美股掃描開始（{len(US_WATCHLIST)} 檔）...")

    ensure_yf_warmup()

    def _fetch_one(item):
        name, ticker = item
        return name, fetch(ticker, period="1y")

    us_data = {}
    with ThreadPoolExecutor(max_workers=len(US_WATCHLIST)) as pool:
        for name, df in pool.map(_fetch_one, US_WATCHLIST.items()):
            if df is not None and not df.empty:
                us_data[name] = df

    found = []
    for name, df in us_data.items():
        df   = add_indicators(df)
        sigs = detect_signals(df)
        sc   = score(sigs)
        if abs(sc) < min_score:
            continue
        latest     = df.iloc[-1]
        prev       = df.iloc[-2]
        price      = float(latest["Close"])
        prev_price = float(prev["Close"])
        change_pct = (price - prev_price) / prev_price * 100
        found.append({
            "name": name, "ticker": US_WATCHLIST[name],
            "signals": sigs, "score": sc,
            "price": price, "change_pct": change_pct,
            "vol_ratio":   float(latest.get("Vol_ratio",  1.0)),
            "week52_pct":  float(calc_week52(df)["week52_pct"]),
            "atr_pct":     float(latest.get("ATR_pct",    0.0)),
            "is_holding":  False,
        })
        print(f"  -> {name} 分數={sc}: {[s['msg'] for s in sigs]}")

    _attach_valuation(found)

    if notify:
        now = datetime.now()
        date_str = now.strftime("%m/%d")
        if found:
            sorted_found = sorted(found, key=lambda x: abs(x["score"]), reverse=True)
            data = {
                "date":      now.strftime("%Y-%m-%d"),
                "timestamp": now.strftime("%Y-%m-%d %H:%M"),
                "signals": [
                    {"name": x["name"], "ticker": x["ticker"], "score": x["score"],
                     "price": round(x["price"], 2), "change_pct": round(x["change_pct"], 2),
                     "vol_ratio": round(x["vol_ratio"], 2),
                     "week52_pct": round(x["week52_pct"], 1),
                     "valuation": x.get("valuation", {}),
                     "bear": x.get("bear", []),
                     "signals": [s["msg"] for s in x["signals"]]}
                    for x in sorted_found
                ],
            }
            _US_RESULTS.write_text(json.dumps(data, ensure_ascii=False, indent=2))
            print(f"  美股彙整報告 → 存入 us_scan_results.json（{len(found)} 檔有訊號）")
        else:
            print("  無美股技術訊號")

    return found


if __name__ == "__main__":
    run_us_scan()
