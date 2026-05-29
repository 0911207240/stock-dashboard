"""每日掃描腳本，可用排程每天自動執行"""
import math
from datetime import datetime
from data_fetcher import fetch_all, WATCHLIST
from analyzer import add_indicators, detect_signals, score
from line_notifier import send, build_signal_message, build_summary_message
from portfolio import HOLDINGS, calc_summary, build_portfolio_message


def run_scan(min_score: int = 2, notify: bool = True):
    print(f"\n[{datetime.now().strftime('%Y-%m-%d %H:%M')}] 開始掃描...")
    all_data = fetch_all(period="1y")

    # 1. 持股日報（優先推播）
    if notify:
        summary = calc_summary(dict(all_data))
        portfolio_msg = build_portfolio_message(summary)
        send(portfolio_msg)
        print("  持股日報已推播")

    # 2. 技術訊號掃描
    found = []
    portfolio_names = set(HOLDINGS.keys())  # HOLDINGS is dict of {name: {shares, cost}}

    for name, df in all_data.items():
        df = add_indicators(df)
        sigs = detect_signals(df)
        sc = score(sigs)

        # 持股降低門檻（分數>=1 就通知），其餘維持 min_score
        threshold = 1 if name in portfolio_names else min_score
        if abs(sc) >= threshold:
            latest = df.iloc[-1]
            prev = df.iloc[-2]
            price = float(latest["Close"])
            prev_price = float(prev["Close"])
            change_pct = (price - prev_price) / prev_price * 100
            vol_ratio = float(latest["Vol_ratio"]) if not math.isnan(latest["Vol_ratio"]) else 1.0
            year_high = float(df["Close"].max())
            year_low = float(df["Close"].min())
            week52_pct = (price - year_low) / (year_high - year_low) * 100 if year_high != year_low else 50.0
            atr_pct = float(latest["ATR_pct"]) if not math.isnan(latest["ATR_pct"]) else 0.0
            ticker = WATCHLIST[name]
            found.append({
                "name": name, "ticker": ticker, "signals": sigs, "score": sc,
                "price": price, "change_pct": change_pct,
                "vol_ratio": vol_ratio, "week52_pct": week52_pct, "atr_pct": atr_pct,
                "is_holding": name in portfolio_names,
            })
            print(f"  -> {name} ({ticker}) 分數={sc}: {[s['msg'] for s in sigs]}")

    if not found:
        print("  無符合條件的股票")
        if notify:
            send(f"[{datetime.now().strftime('%m/%d')} 掃描完成] 無額外技術訊號")
        return

    if notify:
        date_str = datetime.now().strftime("%m/%d")
        sorted_found = sorted(found, key=lambda x: (x["is_holding"], abs(x["score"])), reverse=True)
        summary_msg = build_summary_message(sorted_found, date_str)
        success = send(summary_msg)
        print(f"  彙整報告: {'已推播' if success else '推播失敗'}")

    print(f"掃描完成，共 {len(found)} 檔有訊號")
    return found


if __name__ == "__main__":
    run_scan()
