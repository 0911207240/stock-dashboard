"""每日掃描腳本，可用排程每天自動執行"""
from data_fetcher import fetch_all, WATCHLIST
from analyzer import add_indicators, detect_signals, score
from line_notifier import send, build_signal_message
from datetime import datetime

def run_scan(min_score: int = 2, notify: bool = True):
    print(f"\n[{datetime.now().strftime('%Y-%m-%d %H:%M')}] 開始掃描...")
    all_data = fetch_all(period="1y")
    found = []

    for name, df in all_data.items():
        df = add_indicators(df)
        sigs = detect_signals(df)
        sc = score(sigs)

        if abs(sc) >= min_score:
            latest = df.iloc[-1]
            prev = df.iloc[-2]
            price = float(latest["Close"])
            prev_price = float(prev["Close"])
            change_pct = (price - prev_price) / prev_price * 100
            vol_ratio = float(latest["Vol_ratio"]) if not __import__("math").isnan(latest["Vol_ratio"]) else 1.0
            year_high = float(df["Close"].max())
            year_low = float(df["Close"].min())
            week52_pct = (price - year_low) / (year_high - year_low) * 100 if year_high != year_low else 50.0
            ticker = WATCHLIST[name]
            atr_pct = float(latest["ATR_pct"]) if not __import__("math").isnan(latest["ATR_pct"]) else 0.0
            found.append({
                "name": name, "ticker": ticker, "signals": sigs, "score": sc,
                "price": price, "change_pct": change_pct,
                "vol_ratio": vol_ratio, "week52_pct": week52_pct, "atr_pct": atr_pct,
            })
            print(f"  -> {name} ({ticker}) 分數={sc}: {[s['msg'] for s in sigs]}")

    if not found:
        print("  無符合條件的股票")
        if notify:
            send(f"[{datetime.now().strftime('%m/%d')} 每日掃描] 目前無明確訊號")
        return

    if notify:
        for item in sorted(found, key=lambda x: x["score"], reverse=True):
            msg = build_signal_message(
                item["name"], item["ticker"], item["signals"], item["price"],
                item["change_pct"], item["vol_ratio"], item["week52_pct"], item["atr_pct"],
            )
            success = send(msg)
            status = "已推播" if success else "推播失敗"
            print(f"  {item['name']}: {status}")

    print(f"掃描完成，共 {len(found)} 檔有訊號")
    return found


if __name__ == "__main__":
    run_scan()
