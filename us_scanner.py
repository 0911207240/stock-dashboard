"""美股夜盤掃描（台灣時間每日 05:30 執行，對應美股收盤後）"""
from datetime import datetime
from data_fetcher import fetch_all, WATCHLIST
from analyzer import add_indicators, detect_signals, score
from line_notifier import send, build_summary_message

US_WATCHLIST = {k: v for k, v in WATCHLIST.items() if not v.endswith(".TW") and not v.endswith(".TWO")}


def run_us_scan(min_score: int = 2, notify: bool = True):
    print(f"\n[{datetime.now().strftime('%Y-%m-%d %H:%M')}] 美股掃描開始（{len(US_WATCHLIST)} 檔）...")
    all_data = fetch_all(period="1y")
    us_data  = {k: v for k, v in all_data.items() if k in US_WATCHLIST}

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
            "week52_pct":  0.0,
            "atr_pct":     float(latest.get("ATR_pct",    0.0)),
            "is_holding":  False,
        })
        print(f"  -> {name} 分數={sc}: {[s['msg'] for s in sigs]}")

    if notify:
        date_str = datetime.now().strftime("%m/%d")
        if found:
            sorted_found = sorted(found, key=lambda x: abs(x["score"]), reverse=True)
            msg = "🌙 【美股夜盤訊號】\n" + build_summary_message(sorted_found, date_str)
            send(msg)
            print(f"  美股彙整報告已推播（{len(found)} 檔有訊號）")
        else:
            print("  無美股技術訊號")

    return found


if __name__ == "__main__":
    run_us_scan()
