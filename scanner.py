"""每日掃描腳本，可用排程每天自動執行"""
import json
import math
from datetime import datetime
from pathlib import Path

_MORNING_LOCK = Path("morning_lock.json")

def _morning_done_today() -> bool:
    try:
        return json.loads(_MORNING_LOCK.read_text()).get("date") == datetime.now().strftime("%Y-%m-%d")
    except Exception:
        return False

def _mark_morning_done():
    _MORNING_LOCK.write_text(json.dumps({"date": datetime.now().strftime("%Y-%m-%d")}))
from tw_calendar import is_trading_day
from twse_announcements import build_announcement_alert
from earnings_calendar import build_earnings_alert, has_earnings_risk
from data_fetcher import fetch_all, WATCHLIST
from analyzer import add_indicators, detect_signals, score
from line_notifier import send, build_signal_message, build_summary_message, build_daytrade_message
from image_notifier import send_daytrade_image
from portfolio import HOLDINGS, calc_summary, build_portfolio_message, build_alert_message, build_dividend_alert_message, build_rebalance_alert, build_correlation_alert
from daytrade_scorer import get_daytrade_candidates
from push_cooldown import is_cooled_down, mark_pushed
from tdcc_holders import get_holder_signal
from signal_log import save_daytrade_signal, update_daytrade_results, daytrade_win_rate, calc_weekly_performance, calc_monthly_performance, get_stock_win_rate
from backtest import auto_update_weights
from fundamental_filter import prefetch_all
from market_regime import detect_regime


def _check_concentration(candidates: list[dict]) -> str:
    """
    偵測當沖候選是否集中在同一族群（依 SECTORS 反查）
    超過 2 檔屬同族群 → 回傳警示文字，否則回傳空字串
    """
    from data_fetcher import SECTORS
    name_set = {c["name"] for c in candidates}
    warnings = []
    for sector, members in SECTORS.items():
        if sector in ("全部", "我的持股", "台灣電子績優", "低價波段($50以下)"):
            continue
        overlap = name_set & set(members)
        if len(overlap) >= 3:
            warnings.append(f"{sector}（{len(overlap)} 檔：{'、'.join(overlap)}）")
    if warnings:
        return "⚠️ 集中警示：" + "；".join(warnings)
    return ""


def run_scan(min_score: int = 2, notify: bool = True):
    if not is_trading_day():
        print(f"[{datetime.now().strftime('%Y-%m-%d')}] 今日非台灣交易日，跳過掃描")
        return []

    now = datetime.now()
    is_morning = not _morning_done_today()   # 早盤：今日尚未推過早報（GitHub Actions 延遲補償）
    is_midday  = 10 <= now.hour < 16         # 12:30 午盤（寬鬆範圍）
    session    = "午盤" if (is_midday and not is_morning) else "早盤"
    print(f"\n[{now.strftime('%Y-%m-%d %H:%M')}] {session}掃描開始...")
    from concurrent.futures import ThreadPoolExecutor
    from data_fetcher import fetch_all_institutional, fetch_all_margin, fetch_taifex_futures

    all_data = fetch_all(period="1y")

    # 並發計算技術指標（避免重複呼叫）
    with ThreadPoolExecutor(max_workers=8) as _ex:
        analyzed_data = dict(_ex.map(
            lambda item: (item[0], add_indicators(item[1])),
            all_data.items()
        ))

    # 批次抓取籌碼資料 + 台指期（並發執行）
    with ThreadPoolExecutor(max_workers=3) as _ex:
        _inst_f    = _ex.submit(fetch_all_institutional)
        _margin_f  = _ex.submit(fetch_all_margin)
        _futures_f = _ex.submit(fetch_taifex_futures)
        _inst_by_code   = _inst_f.result()
        _margin_by_code = _margin_f.result()
        futures_data    = _futures_f.result()
    if futures_data:
        print(f"  台指期外資：{futures_data.get('futures_desc', '')} 淨口數 {futures_data.get('foreign_net', 0):,}")

    def _tw_code(ticker: str) -> str:
        return ticker.replace(".TW", "").replace(".TWO", "")

    inst_cache = {
        name: _inst_by_code[_tw_code(ticker)]
        for name, ticker in WATCHLIST.items()
        if ticker.endswith(".TW") and _tw_code(ticker) in _inst_by_code
    }
    margin_cache = {
        name: _margin_by_code[_tw_code(ticker)]
        for name, ticker in WATCHLIST.items()
        if ticker.endswith(".TW") and _tw_code(ticker) in _margin_by_code
    }
    print(f"  籌碼資料：法人 {len(inst_cache)} 檔 / 融資 {len(margin_cache)} 檔")

    # 0. 預載基本面快取 + 回查昨日當沖結果 + 偵測大盤狀態
    prefetch_all(WATCHLIST)
    update_daytrade_results(dict(all_data))

    from data_fetcher import fetch_taiex
    taiex_df = fetch_taiex(period="3mo")
    taiex_df = add_indicators(taiex_df) if not taiex_df.empty else taiex_df
    regime   = detect_regime(taiex_df, futures_data=futures_data)
    base_min_score = 40 + regime["min_score_adj"]
    print(f"  大盤狀態：{regime['emoji']} {regime['state']}（門檻 {base_min_score}分）")

    # 1. 持股日報 + 停損/停利緊急警報（早盤才推，午盤略過；多次觸發只推一次）
    total_value  = 0.0
    portfolio_pnl = None
    if notify and is_morning:
        if _morning_done_today():
            print("  早盤報告今日已推播，跳過重複發送")
        else:
            summary = calc_summary(dict(all_data))
            total_value  = summary.get("__total__", {}).get("total_value", 0.0)
            portfolio_pnl = summary.get("__total__", {}).get("total_pnl")
            alert_msg = build_alert_message(summary)
            if alert_msg:
                send(alert_msg)
                print("  ⚠️ 停損/停利警報已推播")
            portfolio_msg = build_portfolio_message(summary)
            send(portfolio_msg)
            print("  持股日報已推播")

            div_msg = build_dividend_alert_message(WATCHLIST)
            if div_msg:
                send(div_msg)
                print("  除息提醒已推播")

            ann_msg = build_announcement_alert(HOLDINGS, WATCHLIST)
            if ann_msg:
                send(ann_msg)
                print("  重大公告已推播")

            earn_msg = build_earnings_alert(HOLDINGS, WATCHLIST)
            if earn_msg:
                send(earn_msg)
                print("  財報警示已推播")

            rebal_msg = build_rebalance_alert(summary)
            if rebal_msg:
                send(rebal_msg)
                print("  再平衡警報已推播")

            corr_msg = build_correlation_alert(dict(all_data))
            if corr_msg:
                send(corr_msg)
                print("  持股相關性警報已推播")

            _mark_morning_done()

    # 2. 技術訊號掃描
    found = []
    portfolio_names = set(HOLDINGS.keys())

    for name, df in analyzed_data.items():
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
        session_tag = "【午盤更新】" if is_midday else ""
        if found:
            sorted_found = sorted(found, key=lambda x: (x["is_holding"], abs(x["score"])), reverse=True)
            summary_msg  = build_summary_message(sorted_found, date_str)
            if session_tag:
                summary_msg = session_tag + "\n" + summary_msg
            success = send(summary_msg)
            print(f"  {session_tag}彙整報告: {'已推播' if success else '推播失敗'}")
        else:
            print(f"  {session_tag}無符合條件的技術訊號，繼續掃描當沖候選...")

    print(f"掃描完成，共 {len(found)} 檔有訊號")

    # 3. 隔日當沖候選（依大盤狀態動態門檻，含冷卻過濾 + 個股歷史勝率調整）
    dt_candidates = get_daytrade_candidates(
        analyzed_data, WATCHLIST,
        inst_cache=inst_cache, margin_cache=margin_cache,
        top_n=10, pre_analyzed=True,
    )
    for c in dt_candidates:
        # 財報前 3 天內自動降分（高不確定性）
        if has_earnings_risk(c["name"], c["ticker"], days_ahead=3):
            c["score"] = int(c["score"] * 0.7)
            c["signals"].insert(0, "⚠️ 財報前3天，風險偏高")
        sr = get_stock_win_rate(c["name"])
        if sr["win_rate"] is not None:
            # 勝率 >= 60% 加分；< 40% 扣分，並標記
            if sr["win_rate"] >= 60:
                c["score"] = min(100, int(c["score"] * 1.1))
                c["signals"].insert(0, f"歷史勝率{sr['win_rate']}%↑({sr['total']}筆)")
            elif sr["win_rate"] < 40:
                c["score"] = int(c["score"] * 0.85)
                c["signals"].insert(0, f"⚠️歷史勝率偏低{sr['win_rate']}%({sr['total']}筆)")
        c["hist_win_rate"] = sr["win_rate"]

        # 集保戶數（每週更新，大戶增持加分，減持扣分）
        holder = get_holder_signal(c["ticker"])
        if holder["signal"] == "accumulate":
            c["score"] = min(100, c["score"] + 5)
            c["signals"].insert(0, holder["label"])
        elif holder["signal"] == "distribute":
            c["score"] = max(0, c["score"] - 5)
            c["signals"].insert(0, holder["label"])

    fresh_candidates = [
        c for c in dt_candidates
        if not is_cooled_down(c["name"], c["score"]) and c["score"] >= base_min_score
    ]
    push_list = fresh_candidates[:5]

    if push_list:
        for c in push_list:
            mark_pushed(c["name"], c["score"])
            # 資金配置：每筆最多虧總資產 1%，計算建議張數
            if total_value > 0:
                risk_per_share = c["entry_mid"] - c["stop"]
                if risk_per_share > 0:
                    c["suggested_lots"] = max(1, int(total_value * 0.01 / (risk_per_share * 1000)))
                else:
                    c["suggested_lots"] = 1
        save_daytrade_signal(push_list)

        # 部位集中警示：同族群超過2檔 → 附加提示
        concentration_warning = _check_concentration(push_list)

        if notify:
            date_str = datetime.now().strftime("%m/%d")
            success = send_daytrade_image(push_list, date_str, regime, concentration_warning)
            if not success:
                dt_msg = build_daytrade_message(push_list, date_str, regime, concentration_warning)
                success = send(dt_msg)
            print(f"  當沖候選 Top{len(push_list)}（{regime['state']}，門檻{base_min_score}）：{'已推播' if success else '推播失敗'}")
        else:
            print(f"  當沖候選：{', '.join(c['name'] for c in push_list)}")
    else:
        print(f"  無當沖候選（{regime['state']}，門檻{base_min_score}，或全在冷卻期）")

    # 每週一：績效對帳 + 勝率統計 + 回測更新評分權重
    if notify and datetime.now().weekday() == 0:
        stats = daytrade_win_rate()
        perf  = calc_weekly_performance(taiex_df=taiex_df, weeks=1)

        def _sign(v): return "+" if v >= 0 else ""

        stats_lines = ["📊 當沖推播週報"]

        # 績效對帳區塊
        if perf["trades"] > 0:
            exc = perf["excess_return"]
            exc_tag = f"超額 {_sign(exc)}{exc}%" if exc != 0 else "與大盤持平"
            stats_lines += [
                f"",
                f"【近7日績效】{perf['trades']} 筆已結案",
                f"勝率 {perf['win_rate']}%　每筆均報酬 {_sign(perf['avg_return'])}{perf['avg_return']}%",
                f"大盤同期 {_sign(perf['taiex_return'])}{perf['taiex_return']}%　{exc_tag}",
            ]

        # 累計統計
        cum_sign = "+" if stats.get("avg_return", 0) >= 0 else ""
        stats_lines += [
            f"",
            f"【累計】{stats['total']} 筆已結案",
            f"停利② {stats['tp2']} 筆　停利① {stats['tp1']} 筆　停損 {stats['stop']} 筆",
            f"勝率 {stats['win_rate']}%　平均報酬 {cum_sign}{stats.get('avg_return', 0)}%",
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

    # 每月 1 日：月報
    if notify and datetime.now().day == 1:
        mperf = calc_monthly_performance(taiex_df=taiex_df)
        msummary = calc_summary(dict(all_data))
        mtotal = msummary.get("__total__", {})
        mv = mtotal.get("total_value", 0)
        mpnl = mtotal.get("total_pnl")

        def _s(v): return "+" if v >= 0 else ""

        mlines = [f"📅 【{mperf['month_str']}月報】"]
        mlines += [
            "",
            f"【持股現況】",
            f"總市值：${mv:,.0f}",
        ]
        if mpnl is not None:
            mlines.append(f"未實現損益：{_s(mpnl)}${mpnl:,.0f}")

        if mperf["trades"] > 0:
            exc = mperf["excess_return"]
            exc_tag = f"超額 {_s(exc)}{exc}%" if exc != 0 else "與大盤持平"
            mlines += [
                "",
                f"【當月當沖績效】{mperf['trades']} 筆已結案",
                f"停利② {mperf['tp2']} 筆　停利① {mperf['tp1']} 筆　停損 {mperf['stop']} 筆",
                f"勝率 {mperf['win_rate']}%　平均報酬 {_s(mperf['avg_return'])}{mperf['avg_return']}%",
                f"大盤同期 {_s(mperf['taiex_return'])}{mperf['taiex_return']}%　{exc_tag}",
            ]
        else:
            mlines.append("\n【當月當沖】無已結案紀錄")

        send("\n".join(mlines))
        print(f"  月報已推播（{mperf['month_str']}）")

    # 大盤快照（每次掃描都存，供復盤）
    if not taiex_df.empty:
        from market_log import save_market_snapshot
        from sector_rotation import calc_sector_momentum
        from data_fetcher import SECTORS
        taiex_close = float(taiex_df.iloc[-1]["Close"])
        taiex_chg   = (
            (taiex_close - float(taiex_df.iloc[-2]["Close"])) / float(taiex_df.iloc[-2]["Close"]) * 100
            if len(taiex_df) >= 2 else 0.0
        )
        top_sectors = calc_sector_momentum(analyzed_data, SECTORS)
        save_market_snapshot(
            taiex_close    = taiex_close,
            taiex_chg_pct  = taiex_chg,
            regime         = regime,
            futures_data   = futures_data,
            top_sectors    = top_sectors,
            portfolio_value= total_value if total_value > 0 else None,
            portfolio_pnl  = portfolio_pnl,
        )
        print("  大盤快照已儲存")

    return found


if __name__ == "__main__":
    run_scan()
