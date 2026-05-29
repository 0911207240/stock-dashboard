"""每日掃描腳本，可用排程每天自動執行"""
import math
from datetime import datetime
from data_fetcher import fetch_all, WATCHLIST
from analyzer import add_indicators, detect_signals, score
from line_notifier import send, build_signal_message, build_summary_message, build_daytrade_message
from portfolio import HOLDINGS, calc_summary, build_portfolio_message
from daytrade_scorer import get_daytrade_candidates
from push_cooldown import is_cooled_down, mark_pushed
from signal_log import save_daytrade_signal, update_daytrade_results, daytrade_win_rate
from backtest import auto_update_weights
from fundamental_filter import prefetch_all


def run_scan(min_score: int = 2, notify: bool = True):
    print(f"\n[{datetime.now().strftime('%Y-%m-%d %H:%M')}] 開始掃描...")
    all_data = fetch_all(period="1y")

    # 0. 預載基本面快取（7天TTL，過期才重抓）+ 回查昨日當沖結果
    prefetch_all(WATCHLIST)
    update_daytrade_results(dict(all_data))

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

    if notify:
        date_str = datetime.now().strftime("%m/%d")
        if found:
            sorted_found = sorted(found, key=lambda x: (x["is_holding"], abs(x["score"])), reverse=True)
            summary_msg = build_summary_message(sorted_found, date_str)
            success = send(summary_msg)
            print(f"  彙整報告: {'已推播' if success else '推播失敗'}")
        else:
            print("  無符合條件的技術訊號，繼續掃描當沖候選...")

    print(f"掃描完成，共 {len(found)} 檔有訊號")

    # 3. 隔日當沖候選 Top5（含冷卻過濾）
    dt_candidates = get_daytrade_candidates(dict(all_data), WATCHLIST, top_n=10)
    # Fix 7：過濾冷卻期內的股票
    fresh_candidates = []
    for c in dt_candidates:
        if not is_cooled_down(c["name"], c["score"]):
            fresh_candidates.append(c)
    push_list = fresh_candidates[:5]

    if push_list:
        for c in push_list:
            mark_pushed(c["name"], c["score"])
        save_daytrade_signal(push_list)
        if notify:
            date_str = datetime.now().strftime("%m/%d")
            dt_msg = build_daytrade_message(push_list, date_str)
            success = send(dt_msg)
            print(f"  當沖候選（冷卻後）Top{len(push_list)}：{'已推播' if success else '推播失敗'}")
        else:
            print(f"  當沖候選（冷卻後）：{', '.join(c['name'] for c in push_list)}")
    else:
        print("  無新的當沖候選（全在冷卻期或無符合條件）")

    # 每週一：推播勝率統計 + 執行回測更新評分權重
    if notify and datetime.now().weekday() == 0:
        stats = daytrade_win_rate()
        sign  = "+" if stats.get("avg_return", 0) >= 0 else ""
        stats_lines = [
            f"📊 當沖推播週報",
            f"累計 {stats['total']} 筆已結案",
            f"停利② {stats['tp2']} 筆　停利① {stats['tp1']} 筆　停損 {stats['stop']} 筆",
            f"勝率 {stats['win_rate']}%　平均報酬 {sign}{stats.get('avg_return', 0)}%",
        ]

        wt = auto_update_weights(dict(all_data), WATCHLIST)
        if wt["updated"]:
            nw = wt["new_weights"]
            ow = wt["old_weights"]
            changed = [f"{k} {ow[k]}→{nw[k]}" for k in nw if nw[k] != ow[k]]
            stats_lines.append("")
            stats_lines.append(f"🔧 評分權重已更新（{wt['stocks_tested']} 檔 / {wt['total_trades']} 筆回測）")
            if changed:
                stats_lines.append("  " + "　".join(changed))
            else:
                stats_lines.append("  權重無變動")
            print(f"  評分權重更新：{wt['new_weights']}")
        else:
            stats_lines.append(f"  權重未更新：{wt.get('reason', '')}")

        if stats["total"] >= 5 or wt["updated"]:
            send("\n".join(stats_lines))
            print(f"  週報已推播（勝率 {stats['win_rate']}%）")

    return found


if __name__ == "__main__":
    run_scan()
