"""每日定時推播 — 當沖候選 + 技術訊號彙整"""
from datetime import datetime

from tw_calendar import is_trading_day
from data_fetcher import fetch_all, fetch_all_institutional, fetch_all_margin, WATCHLIST
from analyzer import add_indicators, detect_signals, score as score_signals
from daytrade_scorer import get_daytrade_candidates
from market_regime import detect_regime
from line_notifier import send, build_daytrade_message, build_summary_message


def run_push(push_type: str = "morning") -> str:
    """執行推播，回傳結果摘要字串"""
    if not is_trading_day():
        return "非交易日，跳過"

    date_str = datetime.now().strftime("%m/%d")
    results = []

    # ── 大盤狀態 ──────────────────────────────────────
    try:
        regime = detect_regime()
    except Exception:
        regime = None

    # ── 所有資料一次抓 ────────────────────────────────
    try:
        all_data = fetch_all(period="6mo")
    except Exception as e:
        return f"資料抓取失敗：{e}"

    # ── 當沖候選（早盤才推） ──────────────────────────
    if push_type in ("morning", "all"):
        try:
            inst_cache   = fetch_all_institutional()
            margin_cache = fetch_all_margin()
        except Exception:
            inst_cache, margin_cache = {}, {}

        try:
            candidates = get_daytrade_candidates(
                all_data=all_data,
                watchlist=WATCHLIST,
                inst_cache=inst_cache,
                margin_cache=margin_cache,
                top_n=10,
            )
            if candidates:
                msg = build_daytrade_message(candidates, date_str, regime=regime)
                send(msg)
                results.append(f"當沖候選 {len(candidates)} 檔")
            else:
                results.append("當沖候選：無符合條件")
        except Exception as e:
            results.append(f"當沖候選失敗：{e}")

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
