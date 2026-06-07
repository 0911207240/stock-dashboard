"""每日定時推播 — 當沖候選 + 技術訊號彙整"""
from datetime import datetime

from tw_calendar import is_trading_day
from data_fetcher import fetch_all, fetch_all_institutional, fetch_all_margin, WATCHLIST, SECTORS
from analyzer import add_indicators, detect_signals, score as score_signals
from daytrade_scorer import get_daytrade_candidates
from market_regime import detect_regime
from line_notifier import send, build_daytrade_message, build_summary_message
from sector_rotation import (
    calc_sector_momentum, build_sector_morning_note,
    build_sector_weekly_report, calc_holding_correlation, build_correlation_warning,
)
from earnings_calendar import build_earnings_alert


def run_push(push_type: str = "morning") -> str:
    """執行推播，回傳結果摘要字串"""
    if push_type == "weekly":
        return _run_weekly_push()
    if push_type == "aftermarket":
        return _run_aftermarket_push()
    if not is_trading_day():
        return "非交易日，跳過"

    date_str = datetime.now().strftime("%m/%d")
    results = []

    # ── 所有資料一次抓 ────────────────────────────────
    try:
        all_data = fetch_all(period="6mo")
    except Exception as e:
        return f"資料抓取失敗：{e}"

    # ── 大盤狀態（需要 add_indicators 後的 0050 / TAIEX）──
    market_df = None
    regime    = None
    try:
        from data_fetcher import fetch as _fetch
        taiex_df  = _fetch("^TWII", period="6mo")
        market_df = all_data.get("台灣50") or taiex_df
        if taiex_df is not None and not taiex_df.empty:
            taiex_df = add_indicators(taiex_df)
        from data_fetcher import fetch_taifex_futures
        futures_data = fetch_taifex_futures()
        regime = detect_regime(taiex_df, futures_data=futures_data if futures_data else None)
    except Exception:
        regime = None

    # ── 當沖候選（早盤才推） ──────────────────────────
    if push_type in ("morning", "all"):
        try:
            inst_cache   = fetch_all_institutional()
            margin_cache = fetch_all_margin()
        except Exception:
            inst_cache, margin_cache = {}, {}

        try:
            sector_list = calc_sector_momentum(all_data, SECTORS)
        except Exception:
            sector_list = []

        try:
            candidates = get_daytrade_candidates(
                all_data=all_data,
                watchlist=WATCHLIST,
                inst_cache=inst_cache,
                margin_cache=margin_cache,
                top_n=10,
                market_df=market_df,
                regime=regime,
            )
            if candidates:
                sector_note = build_sector_morning_note(sector_list)
                msg = build_daytrade_message(candidates, date_str, regime=regime,
                                             sector_note=sector_note)
                send(msg)
                results.append(f"當沖候選 {len(candidates)} 檔")
            else:
                results.append("當沖候選：無符合條件")
        except Exception as e:
            results.append(f"當沖候選失敗：{e}")

        # 財報警示（持股中有財報的才推）
        try:
            from portfolio_manager import load_holdings
            holdings = load_holdings()
            earnings_msg = build_earnings_alert(holdings, WATCHLIST, days_ahead=5)
            if earnings_msg:
                send(earnings_msg)
                results.append("財報警示已推播")
        except Exception:
            pass

    # ── 技術訊號彙整（早盤＋午盤） ────────────────────
    try:
        found = []
        for name, df in all_data.items():
            if df is None or df.empty:
                continue
            df = add_indicators(df)
            sigs = detect_signals(df)
            if not sigs:
                continue
            s = score_signals(sigs)
            latest = df.iloc[-1]
            prev   = df.iloc[-2] if len(df) > 1 else latest
            chg    = (float(latest["Close"]) - float(prev["Close"])) / float(prev["Close"]) * 100
            found.append({
                "name": name,
                "ticker": WATCHLIST.get(name, ""),
                "price": float(latest["Close"]),
                "change_pct": chg,
                "score": s,
                "signals": sigs,
                "is_holding": False,
            })

        if found:
            msg = build_summary_message(found, date_str)
            send(msg)
            results.append(f"技術訊號 {len(found)} 檔")
        else:
            results.append("技術訊號：無")
    except Exception as e:
        results.append(f"技術訊號失敗：{e}")

    return "；".join(results)


def _run_weekly_push() -> str:
    """週報：本週漲跌排行 + 強勢 / 弱勢股 + 籌碼動向"""
    from line_notifier import build_weekly_message, send

    date_str = datetime.now().strftime("%m/%d")

    try:
        all_data = fetch_all(period="1mo")
    except Exception as e:
        return f"週報資料抓取失敗：{e}"

    weekly = []
    for name, df in all_data.items():
        if df is None or df.empty or len(df) < 6:
            continue
        try:
            df = __import__("analyzer").add_indicators(df)
            latest   = df.iloc[-1]
            week_ago = df.iloc[-6]   # 約5個交易日前
            close    = float(latest["Close"])
            ref      = float(week_ago["Close"])
            chg_w    = (close - ref) / ref * 100

            # 技術面狀態
            ma5  = float(latest.get("MA5",  close) or close)
            ma20 = float(latest.get("MA20", close) or close)
            ma60 = float(latest.get("MA60", close) or close)
            rsi  = float(latest.get("RSI",  50)    or 50)
            macd_v   = float(latest.get("MACD",        0) or 0)
            macd_sig = float(latest.get("MACD_signal", 0) or 0)

            trend = "多" if ma5 > ma20 > ma60 else ("空" if ma5 < ma20 < ma60 else "中")
            macd_bull = macd_v > macd_sig

            weekly.append({
                "name":      name,
                "ticker":    WATCHLIST.get(name, ""),
                "close":     close,
                "chg_w":     chg_w,
                "trend":     trend,
                "macd_bull": macd_bull,
                "rsi":       rsi,
            })
        except Exception:
            continue

    if not weekly:
        return "週報：無資料"

    # 板塊輪動分析
    sector_report = ""
    try:
        sector_list = calc_sector_momentum(all_data, SECTORS)
        sector_report = build_sector_weekly_report(sector_list)
    except Exception:
        pass

    # 持倉相關性分析
    corr_warning = ""
    try:
        from portfolio_manager import load_holdings
        holdings    = load_holdings()
        holding_names = [v["name"] for v in holdings.values()]
        alerts      = calc_holding_correlation(all_data, holding_names)
        corr_warning = build_correlation_warning(alerts)
    except Exception:
        pass

    msg = build_weekly_message(weekly, date_str,
                               sector_report=sector_report,
                               corr_warning=corr_warning)
    send(msg)
    return f"週報推播完成，共 {len(weekly)} 檔"


def _run_aftermarket_push() -> str:
    """盤後推播（下午 1:30）：當日異動股彙整"""
    if not is_trading_day():
        return "非交易日，跳過"

    date_str = datetime.now().strftime("%m/%d")

    try:
        all_data = fetch_all(period="5d")
    except Exception as e:
        return f"盤後資料抓取失敗：{e}"

    gainers, losers, surge = [], [], []

    for name, df in all_data.items():
        if df is None or df.empty or len(df) < 2:
            continue
        try:
            latest    = df.iloc[-1]
            prev      = df.iloc[-2]
            close     = float(latest["Close"])
            prev_c    = float(prev["Close"])
            chg_pct   = (close - prev_c) / prev_c * 100
            vol_today = float(latest.get("Volume", 0))
            vol_prev  = float(prev.get("Volume", 1))
            vol_ratio = vol_today / vol_prev if vol_prev > 0 else 1.0

            item = {"name": name, "close": close,
                    "chg_pct": chg_pct, "vol_ratio": vol_ratio}

            if chg_pct >= 3.0:
                gainers.append(item)
            elif chg_pct <= -3.0:
                losers.append(item)

            if vol_ratio >= 2.5 and abs(chg_pct) >= 1.5:
                surge.append(item)
        except Exception:
            continue

    gainers.sort(key=lambda x: -x["chg_pct"])
    losers.sort(key=lambda x: x["chg_pct"])
    surge.sort(key=lambda x: -x["vol_ratio"])

    if not gainers and not losers and not surge:
        return "盤後無顯著異動"

    lines = [f"📊 盤後異動彙整（{date_str}）", ""]

    if gainers:
        lines.append("🔴 強勢股（+3%↑）")
        for d in gainers[:5]:
            lines.append(f"  {d['name']} +{d['chg_pct']:.1f}%  ${d['close']:.1f}")
        lines.append("")

    if losers:
        lines.append("🟢 弱勢股（-3%↓）")
        for d in losers[:5]:
            lines.append(f"  {d['name']} {d['chg_pct']:.1f}%  ${d['close']:.1f}")
        lines.append("")

    if surge:
        lines.append("🔥 爆量異動（量比≥2.5x）")
        for d in surge[:5]:
            arrow = "▲" if d["chg_pct"] >= 0 else "▼"
            lines.append(
                f"  {d['name']} {arrow}{abs(d['chg_pct']):.1f}%  量比 {d['vol_ratio']:.1f}x"
            )

    lines.append("\n⚠️ 資料 T+1，僅供參考")

    from line_notifier import send
    send("\n".join(lines))
    return f"盤後推播：強勢 {len(gainers)} 檔 / 弱勢 {len(losers)} 檔 / 爆量 {len(surge)} 檔"
